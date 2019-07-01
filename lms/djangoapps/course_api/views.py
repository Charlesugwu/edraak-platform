"""
Course API Views
"""

import requests
from urlparse import urljoin

from django.core.exceptions import ValidationError
from django.conf import settings
from django.http import Http404
from django.utils.translation import get_language, ugettext as _
from django.db.models import Q
from django.db import transaction
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response

from edxmako.shortcuts import marketing_link
from edraak_misc.utils import get_courses_marketing_details
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.lib.api.paginators import NamespacedPageNumberPagination
from openedx.core.lib.api.view_utils import view_auth_classes, DeveloperErrorViewMixin
from .api import course_detail, list_courses
from .forms import CourseDetailGetForm, CourseListGetForm
from .serializers import CourseSerializer, CourseDetailSerializer, \
    MarketingCourseDetailSerializer
from edraak_specializations.models import CourseSpecializationInfo


@view_auth_classes(is_authenticated=False)
class CourseDetailView(DeveloperErrorViewMixin, RetrieveAPIView):
    """
    **Use Cases**

        Request details for a course

    **Example Requests**

        GET /api/courses/v1/courses/{course_key}/

    **Response Values**

        Body consists of the following fields:

        * effort: A textual description of the weekly hours of effort expected
            in the course.
        * end: Date the course ends, in ISO 8601 notation
        * enrollment_end: Date enrollment ends, in ISO 8601 notation
        * enrollment_start: Date enrollment begins, in ISO 8601 notation
        * id: A unique identifier of the course; a serialized representation
            of the opaque key identifying the course.
        * media: An object that contains named media items.  Included here:
            * course_image: An image to show for the course.  Represented
              as an object with the following fields:
                * uri: The location of the image
        * name: Name of the course
        * number: Catalog number of the course
        * org: Name of the organization that owns the course
        * overview: A possibly verbose HTML textual description of the course.
            Note: this field is only included in the Course Detail view, not
            the Course List view.
        * short_description: A textual description of the course
        * start: Date the course begins, in ISO 8601 notation
        * start_display: Readably formatted start of the course
        * start_type: Hint describing how `start_display` is set. One of:
            * `"string"`: manually set by the course author
            * `"timestamp"`: generated from the `start` timestamp
            * `"empty"`: no start date is specified
        * pacing: Course pacing. Possible values: instructor, self

        Deprecated fields:

        * blocks_url: Used to fetch the course blocks
        * course_id: Course key (use 'id' instead)

    **Parameters:**

        username (optional):
            The username of the specified user for whom the course data
            is being accessed. The username is not only required if the API is
            requested by an Anonymous user.

    **Returns**

        * 200 on success with above fields.
        * 400 if an invalid parameter was sent or the username was not provided
          for an authenticated request.
        * 403 if a user who does not have permission to masquerade as
          another user specifies a username other than their own.
        * 404 if the course is not available or cannot be seen.

        Example response:

            {
                "blocks_url": "/api/courses/v1/blocks/?course_id=edX%2Fexample%2F2012_Fall",
                "media": {
                    "course_image": {
                        "uri": "/c4x/edX/example/asset/just_a_test.jpg",
                        "name": "Course Image"
                    }
                },
                "description": "An example course.",
                "end": "2015-09-19T18:00:00Z",
                "enrollment_end": "2015-07-15T00:00:00Z",
                "enrollment_start": "2015-06-15T00:00:00Z",
                "course_id": "edX/example/2012_Fall",
                "name": "Example Course",
                "number": "example",
                "org": "edX",
                "overview: "<p>A verbose description of the course.</p>"
                "start": "2015-07-17T12:00:00Z",
                "start_display": "July 17, 2015",
                "start_type": "timestamp",
                "pacing": "instructor"
            }
    """

    serializer_class = CourseDetailSerializer

    def get_serializer_context(self):
        context = super(CourseDetailView, self).get_serializer_context()

        calculate_completion = self.request.GET.get('calculate_completion') in ['true', 'True']
        context['calculate_completion'] = calculate_completion

        return context

    def get_object(self):
        """
        Return the requested course object, if the user has appropriate
        permissions.
        """
        course_key_string = self.kwargs['course_key_string']
        try:
            course_key = CourseKey.from_string(course_key_string)
        except InvalidKeyError:
            error_string = _("{course_key} is not a valid course key")
            raise ValidationError(
                error_string.format(
                    course_key=unicode(course_key_string)))

        try:
            course_overview = CourseOverview.get_from_id(course_key)
        except CourseOverview.DoesNotExist:
            raise Http404(_("Course not found."))
        return course_overview


@view_auth_classes(is_authenticated=False)
class CourseListView(DeveloperErrorViewMixin, ListAPIView):
    """
    **Use Cases**

        Request information on all courses visible to the specified user.

    **Example Requests**

        GET /api/courses/v1/courses/

    **Response Values**

        Body comprises a list of objects as returned by `CourseDetailView`.

    **Parameters**

        username (optional):
            The username of the specified user whose visible courses we
            want to see. The username is not required only if the API is
            requested by an Anonymous user.

        org (optional):
            If specified, visible `CourseOverview` objects are filtered
            such that only those belonging to the organization with the
            provided org code (e.g., "HarvardX") are returned.
            Case-insensitive.

        mobile (optional):
            If specified, only visible `CourseOverview` objects that are
            designated as mobile_available are returned.

    **Returns**

        * 200 on success, with a list of course discovery objects as returned
          by `CourseDetailView`.
        * 400 if an invalid parameter was sent or the username was not provided
          for an authenticated request.
        * 403 if a user who does not have permission to masquerade as
          another user specifies a username other than their own.
        * 404 if the specified user does not exist, or the requesting user does
          not have permission to view their courses.

        Example response:

            [
              {
                "blocks_url": "/api/courses/v1/blocks/?course_id=edX%2Fexample%2F2012_Fall",
                "media": {
                  "course_image": {
                    "uri": "/c4x/edX/example/asset/just_a_test.jpg",
                    "name": "Course Image"
                  }
                },
                "description": "An example course.",
                "end": "2015-09-19T18:00:00Z",
                "enrollment_end": "2015-07-15T00:00:00Z",
                "enrollment_start": "2015-06-15T00:00:00Z",
                "course_id": "edX/example/2012_Fall",
                "name": "Example Course",
                "number": "example",
                "org": "edX",
                "start": "2015-07-17T12:00:00Z",
                "start_display": "July 17, 2015",
                "start_type": "timestamp"
              }
            ]
    """

    pagination_class = NamespacedPageNumberPagination
    serializer_class = CourseSerializer

    @transaction.non_atomic_requests
    def dispatch(self, request, *args, **kwargs):
        return super(CourseListView, self).dispatch(request, *args, **kwargs)

    def get_serializer_context(self):
        context = super(CourseListView, self).get_serializer_context()

        calculate_completion = self.request.GET.get('calculate_completion') in ['true', 'True']
        context['calculate_completion'] = calculate_completion

        return context

    def get_queryset(self):
        """
        Return a list of courses visible to the user.
        """
        form = CourseListGetForm(self.request.query_params, initial={'requesting_user': self.request.user})
        if not form.is_valid():
            raise ValidationError(form.errors)

        return list_courses(
            self.request,
            form.cleaned_data['username'],
            org=form.cleaned_data['org'],
            filter_=form.cleaned_data['filter_'],
        )


class MarketingCourseDetailView(CourseDetailView):
    """
    **Use Cases**

        Request marketing details for a course

    **Example Requests**

        GET /api/courses/v1/courses/{course_key}/

    **Response Values**

        Body consists of the following fields:

        * effort: A textual description of the weekly hours of effort expected
            in the course.
        * end: Date the course ends, in ISO 8601 notation
        * enrollment_end: Date enrollment ends, in ISO 8601 notation
        * enrollment_start: Date enrollment begins, in ISO 8601 notation
        * id: A unique identifier of the course; a serialized representation
            of the opaque key identifying the course.
        * media: An object that contains named media items.  Included here:
            * course_image: An image to show for the course.  Represented
              as an object with the following fields:
                * uri: The location of the image
        * name: Name of the course
        * number: Catalog number of the course
        * org: Name of the organization that owns the course
        * overview: A possibly verbose HTML textual description of the course.
            Note: this field is only included in the Course Detail view, not
            the Course List view.
        * short_description: A textual description of the course
        * start: Date the course begins, in ISO 8601 notation
        * start_display: Readably formatted start of the course
        * start_type: Hint describing how `start_display` is set. One of:
            * `"string"`: manually set by the course author
            * `"timestamp"`: generated from the `start` timestamp
            * `"empty"`: no start date is specified
        * pacing: Course pacing. Possible values: instructor, self

        Deprecated fields:

        * blocks_url: Used to fetch the course blocks
        * course_id: Course key (use 'id' instead)

    **Parameters:**

        username (optional):
            The username of the specified user for whom the course data
            is being accessed. The username is not only required if the API is
            requested by an Anonymous user.

    **Returns**

        * 200 on success with above fields.
        * 400 if an invalid parameter was sent or the username was not provided
          for an authenticated request.
        * 403 if a user who does not have permission to masquerade as
          another user specifies a username other than their own.
        * 404 if the course is not available or cannot be seen.

        Example response:

            {
                "blocks_url": "/api/courses/v1/blocks/?course_id=edX%2Fexample%2F2012_Fall",
                "media": {
                    "course_image": {
                        "uri": "/c4x/edX/example/asset/just_a_test.jpg",
                        "name": "Course Image"
                    }
                },
                "description": "An example course.",
                "end": "2015-09-19T18:00:00Z",
                "enrollment_end": "2015-07-15T00:00:00Z",
                "enrollment_start": "2015-06-15T00:00:00Z",
                "course_id": "edX/example/2012_Fall",
                "name": "Example Course",
                "number": "example",
                "org": "edX",
                "overview: "<p>A verbose description of the course.</p>"
                "start": "2015-07-17T12:00:00Z",
                "start_display": "July 17, 2015",
                "start_type": "timestamp",
                "pacing": "instructor"
            }
    """

    serializer_class = MarketingCourseDetailSerializer

    def get_object(self):
        """
        Return the requested course object with marketing details,
        if the user has appropriate permissions.
        """
        course_object = super(MarketingCourseDetailView, self).get_object()

        # NOTE: The course object is mutable
        self.inject_marketing_details(course_object)
        return course_object

    def inject_marketing_details(self, course_object):
        """
        This method will edit the course object values from the
        marketing API. The Marketing values will not be saved,
        so the object will not be edited in the database.

        It returns without editing the object if no marketing details
        found.
        
        :param course_object: The object we want to alter
        """
        course_id = self.kwargs['course_key_string']
        marketing_data = get_courses_marketing_details(
            request=self.request,
            course_ids=[course_id]
        ).get(course_id)
        if marketing_data:
            course_object.effort = marketing_data['effort']
            course_object.display_name = marketing_data['name']
            course_object.course_image_url = marketing_data['course_image']
            course_object.course_video_url = marketing_data['course_video']
            course_object.short_description = marketing_data[
                'short_description_en'] if get_language() == "en" \
                else marketing_data['short_description_ar']
            course_object.overview = marketing_data.get('overview')
            course_object.name_en = marketing_data['name_en']
            course_object.name_ar = marketing_data['name_ar']
