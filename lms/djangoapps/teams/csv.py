"""
CSV processing and generation utilities for Teams LMS app.
"""
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
    headers = get_team_membership_csv_headers(course, response)
    response.write(','.join(headers) + '\n')
    for user_team_data in team_membership_data:
        row = [user_data.get(header, '') for header in headers]
        response.write(','.join(row) + '\n')


def get_team_membership_csv_headers(course):
    headers = ['user', 'mode']
    for teamset in course.team_configuration.teamsets:
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
    course_students = CourseEnrollment.objects.users_enrolled_in(course.id)
    CourseEnrollment.bulk_fetch_enrollment_states(course_students, course.id)

    course_team_memberships = CourseTeamMembership.objects.filter(
        course_id=course.id
    ).selected_related('team').all()
    course_team_memberships_by_user = {
        user: team_memberships
        for user, team_memberships in itertools.groupby(course_team_memberships, lambda ctm: ctm.user)
    }
    team_membership_data = []
    for user in course_students:
        student_teams = {
            team_membership.team.topic_id: team_membership.team.name
            for team_membership in course_team_memberships_by_user.get(user, [])
        }
        student_teams['user'] = user.username
        student_teams['mode'], _ = CourseEnrollment.enrollment_mode_for_user(user, course.id)
        team_membership_data.append(student_teams)
    return team_membership_data

