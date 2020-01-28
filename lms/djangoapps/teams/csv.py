"""
CSV processing and generation utilities for Teams LMS app.
"""

import csv
from django.contrib.auth.models import User
from student.models import CourseEnrollment
from xmodule.modulestore.django import modulestore

from lms.djangoapps.teams.models import CourseTeam, CourseTeamMembership
from .errors import AlreadyOnTeamInCourse, NotEnrolledInCourseForTeam
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


class TeamMemberShipImportManager(object):
    """
    A manager class that is responsible the import process of csv file including validation and creation of
    team_courseteam and teams_courseteammembership objects.
    """

    def __init__(self):
        # the list of validation errors
        self.error_list = []
        self.teamset_names_list = []
        # this is a dictionary of dictionaries that ensures that a student can belong to
        # one and only one team in a teamset
        self.teamset_membership_dictionary = {}
        # dictionary that matches column index to a teamset name. Used when creating teams to get the right teamset
        self.teamset_index_dictionary = {}
        # the currently selected user
        self.user = ''
        self.number_of_record_added = 0
        # stores the course module that will be used to get course metadata
        self.course_module = ''
        # stores the course for which we are populating teams
        self.course = ''
        self.max_erros = 0
        self.max_erros_found = False

    @property
    def import_succeeded(self):
        """
        Helper wrapper that tells us the status of the import
        """
        return len(self.error_list) == 0

    def set_team_membership_from_csv(self, course, input_file):
        """
        Assigns team membership based on the content of an uploaded CSV file.
        Returns true if there were no issues.

        Arguments:
            course (CourseDescriptor): Course module for which team membership needs to be set.
        """
        self.error_list = []
        self.teamset_names_list = []
        self.teamset_membership_dictionary = {}
        self.course = course
        self.course_module = modulestore().get_course(course.id)
        all_rows = [row for row in csv.reader(input_file.read().decode('utf-8').splitlines())]
        header_row = all_rows[0]
        if self.validate_teamsets(header_row):
            # process student rows:
            for i in range(1, len(all_rows)):
                row_data = all_rows[i]
                if row_data[0]:  # avoid processing rows with empty user names (excel copy and paste)
                    user = self.reset_user(row_data[0])
                    if user is None:
                        continue
                    if self.validate_user_entry(user, course) is False:
                        row_data[0] = None
                        continue

                    row_data[0] = user

                    if self.validate_user_to_team(row_data, course) is False:
                        return False

            if len(self.error_list) == 0:
                for i in range(1, len(all_rows)):
                    self.add_user_to_team(all_rows[i], course)
                return True
            else:
                return False
        return False

    def validate_teamsets(self, header_row):
        """
        Validates team set names. Returns true if there are no errors.
        Also populates teh teamset_names_list.
        header_row is the list representation of the header row of the input file. It will have
        the following format:
        user, mode, <teamset_1_name>,...,<teamset_n_name>
        where teamset_X_name must be a valid name of an existing teamset.
        """
        for i in range(2, len(header_row)):
            team_config = self.course_module.teams_configuration
            if not header_row[i] in [ts.teamset_id for ts in team_config.teamsets]:
                self.error_list.append("Teamset named " + header_row[i] + " does not exist.")
                return False
            self.teamset_names_list.append(header_row[i])
            self.teamset_membership_dictionary[i] = []
            self.teamset_index_dictionary[i] = header_row[i]
        return True

    def validate_user_entry(self, user, course):
        """
        Invalid states:
            user not enrolled in course
        Validates user row entry. Returns true if there are no errors.
        user_row is the list representation of an input row. It will have the following formta:
        use_id, enrollment_mode, <Team_Name_1>,...,<Team_Name_n>
        Team_Name_x are optional and can be a sparse list i.e:
        andrew,masters,team1,,team3
        joe,masters,,team2,team3
        """
        if not CourseEnrollment.is_enrolled(user, course.id):
            self.error_list.append('User ' + user.username + ' is not enrolled in this course.')
            return False

        return True

    def validate_user_to_team(self, user_row, course):
        """
        Validates a user entry relative to an existing team.
        user_row is the list representation of an input row. It will have the following formta:
        user_row[0] will contain an edX user object, followed by:
        enrollment_mode, <Team_Name_1>,...,<Team_Name_n>
        Team_Name_x are optional and can be a sparse list i.e:
        [andrew],masters,team1,,team3
        [joe],masters,,team2,team3
        """
        for i in range(2, len(user_row)):
            user = user_row[0]
            team_name = user_row[i]
            if team_name:
                try:
                    # checks for a team inside a specific team set. This way team names can be duplicated across
                    # teamsets
                    team = CourseTeam.objects.get(name=team_name, topic_id=self.teamset_index_dictionary[i])
                except CourseTeam.DoesNotExist:
                    # if a team doesn't exists, the validation doesn't apply to it.
                    import pdb;pdb.set_trace()
                    if user.id in self.teamset_membership_dictionary[i]:
                        if self.add_error_and_check_if_max_exceeded.append(
                            'User ' + user.id + ' is already on a team set.'):
                            return False
                    else:
                        self.teamset_membership_dictionary[i].append(user.id)
                    continue
                max_team_size = self.course_module.teams_configuration.default_max_team_size
                if max_team_size is not None and team.users.count() >= max_team_size:
                    if self.add_error_and_check_if_max_exceeded.append('Team ' + team.team_id + ' is already full.'):
                        return False
                if CourseTeamMembership.user_in_team_for_course( user, self.course.id, team.topic_id):
                    if self.add_error_and_check_if_max_exceeded(
                        'The user ' + self.user.username + ' is already a member of a team inside teamset '
                        + team.topic_id + ' in this course.'
                    ):
                        return False

    def add_error_and_check_if_max_exceeded(self, error_message):
        """
        Adds an error to the error collection.
        :param error_message:
        :return: True if maximum error threshold is exceeded and processing must stop
                 False if maximum error threshold is NOT exceeded and processing can continue
        """
        self.error_list.append(error_message)
        if count(self.error_list) >= self.max_erros:
            self.max_erros_found = True
            return True
        else:
            return False

    def add_user_to_team(self, user_row, course):
        """
        Creates a CourseTeamMembership entry - i.e: a relationship between a user and a team.
        user_row is the list representation of an input row. It will have the following formta:
        use_id, enrollment_mode, <Team_Name_1>,...,<Team_Name_n>
        Team_Name_x are optional and can be a sparse list i.e:
        andrew,masters,team1,,team3
        joe,masters,,team2,team3
        """
        user = user_row[0]
        for i in range(2, len(user_row)):
            team_name = user_row[i]
            if team_name:
                try:
                    # checks for a team inside a specific team set. This way team names can be duplicated across
                    # teamsets
                    team = CourseTeam.objects.get(name=team_name, topic_id=self.teamset_index_dictionary[i])
                except CourseTeam.DoesNotExist:
                    team = CourseTeam.create(name=team_name, course_id=course.id, description='Import from csv',
                                             topic_id=self.teamset_index_dictionary[i]
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
                    import pdb;pdb.set_trace()
                    e = 'bad'
                    throw
                self.number_of_record_added += 1

    def reset_user(self, user_name):
        """
        Resets the class user object variable from the provided username/email/user locator.
        If a matching user is not found, throws exception and stops processing.
        user_name: the user_name/email/user locator
        """
        try:
            return User.objects.get(username=user_name)
        except User.DoesNotExist:
            try:
                return User.objects.get(email=user_name)
            except User.DoesNotExist:
                self.error_list.append('Username or email ' + user_name + ' does not exist.')
                return None
                # TODO - handle user key case
