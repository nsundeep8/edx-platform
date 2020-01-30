"""
CSV processing and generation utilities for Teams LMS app.
"""

import csv
from django.contrib.auth.models import User
from student.models import CourseEnrollment
from xmodule.modulestore.django import modulestore

from lms.djangoapps.teams.models import CourseTeam, CourseTeamMembership
from .errors import AlreadyOnTeamInCourse
from .utils import emit_team_event


def load_team_membership_csv(course, response):
    """
    Load a CSV detailing course membership.

    Arguments:
        course (CourseDescriptor): Course module for which CSV
            download has been requested.
        response (HttpResponse): Django response object to which
            the CSV content will be written.
    """
    # This function needs to be implemented (TODO MST-31).
    _ = course
    not_implemented_message = (
        "Team membership CSV download is not yet implemented."
    )
    response.write(not_implemented_message + "\n")


class TeamMembershipImportManager(object):
    """
    A manager class that is responsible the import process of csv file including validation and creation of
    team_courseteam and teams_courseteammembership objects.
    """

    def __init__(self, course):
        self.validation_errors = []
        self.teamset_ids = []
        self.user_ids_by_teamset_id = {}
        self.teamset_ids = []
        self.number_of_record_added = 0
        # stores the course module that will be used to get course metadata
        self.course_module = ''
        # stores the course for which we are populating teams
        self.course = course
        self.max_errors = 0

    @property
    def import_succeeded(self):
        """
        Helper wrapper that tells us the status of the import
        """
        return not self.validation_errors

    def set_team_membership_from_csv(self, input_file):
        """
        Assigns team membership based on the content of an uploaded CSV file.
        Returns true if there were no issues.
        """
        self.course_module = modulestore().get_course(self.course.id)
        reader = csv.DictReader((line.decode('utf-8').strip() for line in input_file.readlines()))

        self.teamset_ids = reader.fieldnames[2:]
        row_dictionaries = []
        if self.validate_teamsets():
            # process student rows:
            for row in reader:
                username = row['user']
                if not username:
                    continue
                user = self.get_user(username)
                if user is None:
                    continue
                if self.validate_user_enrolled_in_course(user) is False:
                    row['user'] = None
                    continue
                row['user'] = user

                if self.validate_user_to_team(row) is False:
                    return False
                row_dictionaries.append(row)

            if not self.validation_errors:
                for row in row_dictionaries:
                    self.add_user_to_team(row)
                return True
            else:
                return False
        return False

    def validate_teamsets(self):
        """
        Validates team set names. Returns true if there are no errors.
        The following conditions result in errors:
        Teamset does not exist
        Teamset id is duplicated
        Also populates the teamset_names_list.
        header_row is the list of teamset_ids
        """
        teamset_ids = {ts.teamset_id for ts in self.course_module.teams_configuration.teamsets}
        dupe_set = set()
        for teamset_id in self.teamset_ids:
            if teamset_id in dupe_set:
                self.validation_errors.append("Teamset with id " + teamset_id + " is duplicated.")
                return False
            dupe_set.add(teamset_id)
            if teamset_id not in teamset_ids:
                self.validation_errors.append("Teamset with id " + teamset_id + " does not exist.")
                return False
            self.user_ids_by_teamset_id[teamset_id] = {m.user_id for m in CourseTeamMembership.objects.filter
                                                       (team__course_id=self.course.id, team__topic_id=teamset_id)}
        return True

    def validate_user_enrolled_in_course(self, user):
        """
        Invalid states:
            user not enrolled in course
        """
        if not CourseEnrollment.is_enrolled(user, self.course.id):
            self.validation_errors.append('User ' + user.username + ' is not enrolled in this course.')
            return False

        return True

    def validate_user_to_team(self, row):
        """
        Validates a user entry relative to an existing team.
        row is a dictionary where key is column name and value is the row value
        [andrew],masters,team1,,team3
        [joe],masters,,team2,team3
        """
        user = row['user']
        for teamset_id in self.teamset_ids:
            team_name = row[teamset_id]
            if not team_name:
                continue
            try:
                # checks for a team inside a specific team set. This way team names can be duplicated across
                # teamsets
                team = CourseTeam.objects.get(name=team_name, topic_id=teamset_id)
            except CourseTeam.DoesNotExist:
                # if a team doesn't exists, the validation doesn't apply to it.
                all_teamset_user_ids = self.user_ids_by_teamset_id[teamset_id]
                error_message = 'User {} is already on a teamset'.format(user)
                if user.id in all_teamset_user_ids and self.add_error_and_check_if_max_exceeded(error_message):
                    return False
                else:
                    self.user_ids_by_teamset_id[teamset_id].add(user.id)
                    continue
            max_team_size = self.course_module.teams_configuration.default_max_team_size
            if max_team_size is not None and team.users.count() >= max_team_size:
                if self.add_error_and_check_if_max_exceeded('Team ' + team.team_id + ' is already full.'):
                    return False
            if CourseTeamMembership.user_in_team_for_course(user, self.course.id, team.topic_id):
                error_message = 'The user {0} is already a member of a team inside teamset {1} in this course.'.format(
                    user.username, team.topic_id
                )
                if self.add_error_and_check_if_max_exceeded(error_message):
                    return False

    def add_error_and_check_if_max_exceeded(self, error_message):
        """
        Adds an error to the error collection.
        :param error_message:
        :return: True if maximum error threshold is exceeded and processing must stop
                 False if maximum error threshold is NOT exceeded and processing can continue
        """
        self.validation_errors.append(error_message)
        return len(self.validation_errors) >= self.max_errors

    def add_user_to_team(self, user_row):
        """
        Creates a CourseTeamMembership entry - i.e: a relationship between a user and a team.
        user_row is a dictionary where key is column name and value is the row value.
        {'mode': ' masters','topic_0': '','topic_1': 'team 2','topic_2': None,'user': <user_obj>}
         andrew,masters,team1,,team3
        joe,masters,,team2,team3
        """
        user = user_row['user']
        for teamset_id in self.teamset_ids:
            team_name = user_row[teamset_id]
            if not team_name:
                continue
            try:
                # checks for a team inside a specific team set. This way team names can be duplicated across
                # teamsets
                team = CourseTeam.objects.get(name=team_name, topic_id=teamset_id)
            except CourseTeam.DoesNotExist:
                team = CourseTeam.create(
                    name=team_name,
                    course_id=self.course.id,
                    description='Import from csv',
                    topic_id=teamset_id
                )
                team.save()
            try:
                team.add_user(user)
                emit_team_event(
                    'edx.team.learner_added',
                    team.course_id,
                    {
                        'team_id': team.team_id,
                        'user_id': user.id,
                        'add_method': 'added_by_another_user'
                    }
                )
            except AlreadyOnTeamInCourse:
                if self.add_error_and_check_if_max_exceeded(
                    'The user ' + user.username + ' is already a member of a team inside teamset '
                    + team.topic_id + ' in this course.'
                ):
                    return False
            self.number_of_record_added += 1

    def get_user(self, user_name):
        """
        Gets the user object from user_name/email/locator
        user_name: the user_name/email/user locator
        """
        try:
            return User.objects.get(username=user_name)
        except User.DoesNotExist:
            try:
                return User.objects.get(email=user_name)
            except User.DoesNotExist:
                self.validation_errors.append('Username or email ' + user_name + ' does not exist.')
                return None
                # TODO - handle user key case
