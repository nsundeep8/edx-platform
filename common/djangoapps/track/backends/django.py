"""
Event tracker backend that saves events to a Django database.

"""

# TODO: this module is very specific to the event schema, and is only
# brought here for legacy support. It should be updated when the
# schema changes or eventually deprecated.


import logging

from django.db import models
from django.utils.encoding import python_2_unicode_compatible

from track.backends import BaseBackend

log = logging.getLogger('track.backends.django')


LOGFIELDS = [
    'username',
    'ip',
    'event_source',
    'event_type',
    'event',
    'agent',
    'page',
    'time',
    'host',
]


@python_2_unicode_compatible
class TrackingLog(models.Model):
    """
    Defines the fields that are stored in the tracking log database.

    .. pii: Stores a great deal of PII as it is an event tracker of browsing history, unused and empty on edx.org
    .. pii_types: username, ip, other
    .. pii_retirement: retained
    """

    dtcreated = models.DateTimeField(u'creation date', auto_now_add=True)
    username = models.CharField(max_length=32, blank=True)
    ip = models.CharField(max_length=32, blank=True)
    event_source = models.CharField(max_length=32)
    event_type = models.CharField(max_length=512, blank=True)
    event = models.TextField(blank=True)
    agent = models.CharField(max_length=256, blank=True)
    page = models.CharField(max_length=512, blank=True, null=True)
    time = models.DateTimeField(u'event time')
    host = models.CharField(max_length=64, blank=True)

    class Meta(object):
        app_label = 'track'
        db_table = 'track_trackinglog'

    def __str__(self):
        fmt = (
            u"[{self.time}] {self.username}@{self.ip}: "
            u"{self.event_source}| {self.event_type} | "
            u"{self.page} | {self.event}"
        )
        return fmt.format(self=self)


class DjangoBackend(BaseBackend):
    """Event tracker backend that saves to a Django database"""
    def __init__(self, name='default', **options):
        """
        Configure database used by the backend.

        :Parameters:

          - `name` is the name of the database as specified in the project
            settings.

        """
        super(DjangoBackend, self).__init__(**options)
        self.name = name

    def send(self, event):
        field_values = {x: event.get(x, '') for x in LOGFIELDS}
        tldat = TrackingLog(**field_values)
        try:
            tldat.save(using=self.name)
        except Exception as e:  # pylint: disable=broad-except
            log.exception(e)
