"""
CSV processing and generation utilities for Teams LMS app.
"""
from itertools import groupby
from lms.djangoapps.teams.models import CourseTeamMembership
from student.models import CourseEnrollment


def load_team_membership_csv(course, response):
    """
    Load a CSV detailing course membership.

    Arguments:
        course (CourseDescriptor): Course module for which CSV
            download has been requested.
        response (HttpResponse): Django response object to which
            the CSV content will be written.
    """
    team_membership_data = _lookup_team_membership_data(course)
    headers = get_team_membership_csv_headers(course)
    response.write(','.join(headers) + '\n')
    for user_data in team_membership_data:
        row = [user_data.get(header, '') for header in headers]
        response.write(','.join(row) + '\n')


def get_team_membership_csv_headers(course):
    """
    Get headers for team membership csv.
    ['user', 'mode', <teamset_id_1>, ..., ,<teamset_id_n>]
    """
    headers = ['user', 'mode']
    for teamset in sorted(course.teams_configuration.teamsets, key=lambda ts: ts.teamset_id):
        headers.append(teamset.teamset_id)
    return headers


def _lookup_team_membership_data(course):
    """
    Returns a list of dicts, in the following form:
    [
        {
            'user': <username>,
            'mode': <student enrollment mode for the given course>,
            <teamset id>: <team name> for each teamset in which the given user is on a team
        }
        for student in course
    ]
    """
    course_students = CourseEnrollment.objects.users_enrolled_in(course.id).order_by('username')
    CourseEnrollment.bulk_fetch_enrollment_states(course_students, course.id)

    course_team_memberships = CourseTeamMembership.objects.filter(
        team__course_id=course.id
    ).select_related('team', 'user').all()
    teamset_memberships_by_user = _group_teamset_memberships_by_user(course_team_memberships)
    team_membership_data = []
    for user in course_students:
        student_row = teamset_memberships_by_user.get(user, dict())
        student_row['user'] = user.username
        student_row['mode'], _ = CourseEnrollment.enrollment_mode_for_user(user, course.id)
        team_membership_data.append(student_row)
    return team_membership_data

def _group_teamset_memberships_by_user(course_team_memberships):
    """
    Parameters:
        - course_team_memberships: a collection of CourseTeamMemberships
    
    Returns:
        {
            <User>: {
                <teamset_id>: <team_name>
                for CourseTeamMembership in input corresponding to <User>
            }
            per user represented in input
        }
    """
    teamset_memberships_by_user = dict()
    for team_membership in course_team_memberships:
        user = team_membership.user
        if user not in teamset_memberships_by_user:
            teamset_memberships_by_user[user] = dict()
        topic_id = team_membership.team.topic_id
        team_name = team_membership.team.name
        teamset_memberships_by_user[user][topic_id] = team_name
    return teamset_memberships_by_user

