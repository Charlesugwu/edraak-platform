"""
All sort of tests for the University ID app.
"""

from django.test import TestCase, override_settings
from django.core.urlresolvers import NoReverseMatch, reverse
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from bs4 import BeautifulSoup
from mock import Mock, patch
import ddt
from pkg_resources import iter_entry_points  # pylint: disable=no-name-in-module

from student.tests.factories import UserFactory, UserProfileFactory, CourseEnrollmentFactory
from xmodule.tabs import CourseTabList
from student.models import CourseEnrollment
from xmodule.modulestore.tests.factories import CourseFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from student.models import UserProfile

from edraak_university.tab import UniversityIDTab
from edraak_university import helpers
from edraak_university.forms import UniversityIDForm
from edraak_university.models import UniversityID
from edraak_university.tests.factories import UniversityIDFactory


class ModuleStoreTestCaseLoggedIn(ModuleStoreTestCase):
    """
    A base test class to provide helpers to create user (staff or not staff) and log him in.
    """

    LOGIN_STAFF = True
    ENROLL_USER = False

    def setUp(self):
        super(ModuleStoreTestCaseLoggedIn, self).setUp()
        UserProfileFactory.create(user=self.user)  # Avoid missing profile errors on the `get_user_preferences` calls

        self.course = self.create_course()

        if self.LOGIN_STAFF:
            self.login_user(self.user, self.user_password)
        else:
            user, password = self.create_non_staff_user()
            self.user = user
            self.user_password = password
            self.login_user(user, password)

    def create_non_staff_user(self):
        """
        Overrides the non-staff user method.
        """

        password = 'foo'

        user = UserFactory.create(
            password=password,
            is_staff=False,
            is_active=True,
        )

        user.save()

        return user, password

    def create_course(self):
        """
        Creates the initial course for testing.

        This method is to created to enable overriding for customization from children classes.
        """

        return CourseFactory.create()

    def login_user(self, user, password):
        """
        Login and enroll user.
        """
        self.client.post(reverse('login'), {'email': user.email, 'password': password})
        dashboard_res = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard_res, 'Dashboard', msg_prefix='The user should be logged in')

        if self.ENROLL_USER:
            CourseEnrollmentFactory.create(
                user=user, course_id=self.course.id
            )


class SettingsTest(TestCase):
    """
    Sanity checks to ensure correct model configuration.
    """

    def test_url_configs(self):
        try:
            url = reverse('edraak_university:id', kwargs={'course_id': 'edx/demo/2017'})
            self.assertTrue(url.startswith('/university/'), 'Should setup the URL correctly')
        except NoReverseMatch as exception:
            self.fail('The urls are not configured for this module {}'.format(exception))

    def test_enabled_in_test(self):
        feature = settings.FEATURES.get('EDRAAK_UNIVERSITY_APP')
        self.assertTrue(feature, 'The app should be enabled in tests')
        self.assertIn('edraak_university', settings.INSTALLED_APPS)

    def test_disabled_export_modifications(self):
        feature = settings.FEATURES.get('EDRAAK_UNIVERSITY_CSV_EXPORT')
        self.assertFalse(feature, 'The export IDs should be disabled by default')

    def test_tab_installation(self):
        course_tabs = {
            entry_point.name: entry_point.load()
            for entry_point in iter_entry_points(group='openedx.course_tab')
        }

        self.assertIn('university_id', course_tabs,
                      'Course tab is not installed, run `$ pip install -r requirements/edx/local.txt` '
                      'to solve the problem')

        tab_class_name = course_tabs['university_id'].type
        self.assertEquals(tab_class_name, 'university_id', 'Should have the required tab, with a correct tab.type')


@ddt.ddt
class UniversityTabIDTest(ModuleStoreTestCase):
    """
    Unit and integration tests for the tab.
    """

    # This patch disables `SafeCookieData.parse` able to use client.login() without strict checking and errors
    # Other than this, it is not needed in our tests
    CUSTOM_MIDDLEWARE_CLASSES = [
        'django.contrib.sessions.middleware.SessionMiddleware' if cls.endswith('SafeSessionMiddleware') else cls
        for cls in settings.MIDDLEWARE_CLASSES
    ]

    def test_xmodule_field(self):
        course = CourseFactory.create()

        self.assertTrue(hasattr(course, 'enable_university_id'),
                        'The course should have an xmodule enable_university_id field in its field definitions')

        self.assertFalse(course.enable_university_id, 'The feature should be disabled on courses by default')

    @ddt.data(True, False)
    def test_is_enabled_not_logged_in(self, enable_university_id):
        course = CourseFactory.create()
        course.enable_university_id = enable_university_id

        tab = UniversityIDTab(tab_dict={})
        self.assertFalse(tab.is_enabled(course, user=None), 'Should be disabled for all non-logged-in users')

    @ddt.data(True, False)
    def test_is_enabled_not_enrolled(self, enable_university_id):
        user = UserFactory.create()
        course = CourseFactory.create()
        course.enable_university_id = enable_university_id

        tab = UniversityIDTab(tab_dict={})
        self.assertFalse(tab.is_enabled(course, user), 'Should be disabled for all non-enrolled')

    @ddt.unpack
    @ddt.data(
        {'urlconf': 'lms.urls', 'should_enable': False, 'msg': 'Should be disable when user=None in LMS'},
        {'urlconf': 'cms.urls', 'should_enable': True, 'msg': 'Should be enabled when user=None in CMS'},
    )
    def test_enable_if_no_user_cms(self, urlconf, should_enable, msg):
        """
        Ensures that the tab is enabled on CMS when no user is provided.
        """
        with override_settings(ROOT_URLCONF=urlconf):
            with patch.dict(settings.FEATURES, EDRAAK_UNIVERSITY_APP=True):
                course = Mock(enable_university_id=True)
                tab = UniversityIDTab(tab_dict={})
                self.assertEquals(tab.is_enabled(course, user=None), should_enable, msg=msg)

    @ddt.unpack
    @ddt.data(
        {'course_enable_university_id': False, 'should_tab_be_enabled': False},
        {'course_enable_university_id': True, 'should_tab_be_enabled': True},
    )
    def test_is_enabled_enrolled(self, course_enable_university_id, should_tab_be_enabled):
        user = UserFactory.create()
        course = CourseFactory.create()
        course.enable_university_id = course_enable_university_id

        with patch.object(CourseEnrollment, 'is_enrolled', return_value=True):
            tab = UniversityIDTab(tab_dict={})
            self.assertEqual(tab.is_enabled(course, user), should_tab_be_enabled,
                             'Should only be enabled when `enable_university_id` is, even for enrolled users')

            with patch.dict(settings.FEATURES, EDRAAK_UNIVERSITY_APP=False):
                self.assertFalse(tab.is_enabled(course, user),
                                 msg='Setting `EDRAAK_UNIVERSITY_APP=False` should disable the tab regardless.')

    def test_is_added_in_courseware_tabs(self):
        tabs_list = CourseTabList()
        tabs_list.from_json([])

        # The tab should be added anyway,
        # unfortunately the platform don't have a dynamic loading so far
        # check the `CourseTabList` class for more details about this problem
        course = CourseFactory.create()
        course.enable_university_id = False

        tabs_list.initialize_default(course)

        course_tab_types = [tab.type for tab in course.tabs]
        self.assertIn('university_id', course_tab_types)
        self.assertLess(course_tab_types.index('progress'), course_tab_types.index('university_id'),
                        'Should appear after the progress tab')

    def quick_login(self, username, password):
        """
        Quick login, without having to go through the whole edX login process.
        """
        self.client.login(username=username, password=password)

        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Skip to main', msg_prefix='Should be logged in')

    @override_settings(MIDDLEWARE_CLASSES=CUSTOM_MIDDLEWARE_CLASSES)
    def make_course_request(self, enable_university_id):
        """
        Requests a course page with a logged and enrolled user.
        """
        course = CourseFactory.create(enable_university_id=enable_university_id)
        password = 'It is me!'

        user = UserFactory.create(password=password)
        user.save()

        enrollment = CourseEnrollmentFactory.create(course_id=course.id, user=user)
        enrollment.save()

        self.quick_login(user.username, password)

        return self.client.get(reverse('progress', args=[unicode(course.id)]))

    def test_if_tab_shown_in_response(self):
        res = self.make_course_request(enable_university_id=True)
        self.assertContains(res, 'University ID',
                            msg_prefix='Advanced settings is enabled, therefore should show the tab')
        self.assertContains(res, '/university/id/', msg_prefix='The link should appear')

    def test_if_tab_is_hidden_in_response(self):
        res = self.make_course_request(enable_university_id=False)
        self.assertNotContains(res, 'University ID',
                               msg_prefix='Advanced settings is disabled, therefore should NOT show the tab')

        self.assertNotContains(res, '/university/id/', msg_prefix='The link should not appear')


@ddt.ddt
class HelpersTest(ModuleStoreTestCase):
    """
    Tests for the UniversityID helper functions.
    """

    def test_is_feature_enabled_helper(self):
        with patch.dict(settings.FEATURES, EDRAAK_UNIVERSITY_APP=True):
            self.assertTrue(helpers.is_feature_enabled(), 'Should respect the feature')

        with patch.dict(settings.FEATURES, EDRAAK_UNIVERSITY_APP=False):
            self.assertFalse(helpers.is_feature_enabled(), 'Should respect the feature')

        with patch.object(settings, 'FEATURES', {}):
            self.assertFalse(helpers.is_feature_enabled(), 'Should default to False when the feature is missing')

    @patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_APP': True, 'EDRAAK_UNIVERSITY_CSV_EXPORT': False})
    @ddt.data(False, True)
    def test_is_csv_export_enabled_on_course_helper_disabled(self, course_enable_university_id):
        course = Mock(enable_university_id=course_enable_university_id)
        is_export_enabled = helpers.is_csv_export_enabled_on_course(course)
        self.assertFalse(is_export_enabled, 'Export should be disabled when the feature flag is')

    @patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_APP': True, 'EDRAAK_UNIVERSITY_CSV_EXPORT': True})
    def test_is_csv_export_enabled_on_course_helper_enabled(self):
        course_disabled = Mock(enable_university_id=False)
        self.assertFalse(helpers.is_csv_export_enabled_on_course(course_disabled),
                         msg='Export should be disabled when the feature flag is')

        course_enabled = Mock(enable_university_id=True)
        self.assertTrue(helpers.is_csv_export_enabled_on_course(course_enabled),
                        msg='Export should be enabled when all three features are enabled')

    def test_get_university_id_helper(self):
        course = CourseFactory.create()
        user = UserFactory.create()

        self.assertIsNone(helpers.get_university_id(AnonymousUser(), unicode(course.id)))

        self.assertIsNone(helpers.get_university_id(user, unicode(course.id)))

        UniversityID.objects.create(
            course_key=unicode(course.id),
            user=user,
        )

        self.assertIsNotNone(helpers.get_university_id(user, unicode(course.id)), 'Should return an ID')
        self.assertEquals(helpers.get_university_id(user, unicode(course.id)).user_id, user.id,
                          'Should return the correct user_id')

    def test_university_id_is_required_helper(self):
        """
        Tests for both has_valid_university_id and university_id_is_required.
        """
        self.assertFalse(helpers.university_id_is_required(Mock(), Mock(enable_university_id=False)),
                         'The feature is disabled, so the ID should not be required anyway')

        with patch.dict(settings.FEATURES, {'EDRAAK_UNIVERSITY_APP': False}):
            self.assertFalse(helpers.university_id_is_required(Mock(), Mock(enable_university_id=True)),
                             'The platform-specific feature flag is disabled, so the ID should not be required')

        with patch('edraak_university.helpers.get_university_id', return_value=None):
            self.assertTrue(helpers.university_id_is_required(Mock(), Mock(enable_university_id=True)),
                            'The user have no ID and the feature is enabled, so the ID is required.')


@ddt.ddt
class UniversityIDFormTest(TestCase):
    """
    Unit tests for the UniversityIDForm class.
    """

    def setUp(self):
        super(UniversityIDFormTest, self).setUp()

    def get_form(self, overrides=None):
        """
        Get an populated form.
        """
        params = {
            # Initially clean params
            'full_name': 'Mahmoud Salam',
            'university_id': '2010-12-05',
            'section_number': '10'
        }

        if overrides:
            # May add validation errors for testing purposes
            params.update(overrides)

        form = UniversityIDForm(params)
        return form

    def test_initial_data_are_valid(self):
        form = self.get_form()
        self.assertTrue(form.is_valid())
        self.assertFalse(len(form.errors))

    @ddt.unpack
    @ddt.data(
        {'field_name': 'full_name', 'bad_value': '', 'issue': 'is empty'},
        {'field_name': 'full_name', 'bad_value': 'a', 'issue': 'is too short'},
        {'field_name': 'full_name', 'bad_value': 'a' * 60, 'issue': 'is too long'},
        {'field_name': 'university_id', 'bad_value': '123', 'issue': 'is too short'},
        {'field_name': 'university_id', 'bad_value': '2011 501', 'issue': 'has a space'},
        {'field_name': 'university_id', 'bad_value': 'a' * 100, 'issue': 'is too long'},
        {'field_name': 'university_id', 'bad_value': '2011/500', 'issue': 'has a special char'},
        {'field_name': 'section_number', 'bad_value': '', 'issue': 'is empty'},
    )
    def test_field_validators(self, field_name, bad_value, issue):
        invalid_params = {field_name: bad_value}
        form = self.get_form(invalid_params)

        self.assertFalse(form.is_valid(), 'Form is valid, but {field_name} {issue}'.format(
            field_name=field_name,
            issue=issue,
        ))

        self.assertIn(field_name, form.errors)
        self.assertEquals(len(form.errors[field_name]), 1)

    def test_as_div(self):
        form = self.get_form({
            'full_name': '',
        })

        self.assertFalse(form.is_valid(), 'The full_name is empty, the form should not be valid')

        # Emulate an HTML root element
        wrapped = u'<body>{}</body>'.format(form.as_div())
        soup = BeautifulSoup(wrapped, 'html.parser')

        full_name_elem = next(iter(soup.body.children))
        self.assertEquals(full_name_elem.name, 'div', 'Should contain <div> instead of <p> tags')

        label_elem = full_name_elem.label
        errors_elem = full_name_elem.ul
        children = [elem for elem in full_name_elem.children]

        self.assertLess(children.index(label_elem), children.index(errors_elem),
                        '<label> should display before the <ul class="errors"> tag.')


class UniversityIDModelTest(ModuleStoreTestCase):
    """
    Tests for the UniversityID model class.
    """

    def setUp(self):
        super(UniversityIDModelTest, self).setUp()
        self.model = UniversityIDFactory.create(
            user__username='username1',
            user__email='user@example.eu',
            user__profile__name='Mike Wazowski',
            course_key='a/b/c',
            university_id='201711201',
            section_number='10',
        )

        self.profile = UserProfile.objects.get(user=self.model.user)

    def test_unicode(self):
        self.assertEquals(unicode(self.model), 'username1 - a/b/c - 201711201')

    def test_full_name(self):
        self.assertEquals(self.model.get_full_name(), 'Mike Wazowski')

        self.profile.delete()
        self.assertIsNone(self.model.get_full_name())

    def test_get_email(self):
        self.assertEquals(self.model.get_email(), 'user@example.eu')

    def test_get_marked_university_ids(self):
        uni_ids = [
            '20-{}'.format(i)
            for i in ['01a', '10x', '03', '04M ', '04m', '04M\t', '10x ', '02t']
        ]

        course_key = CourseFactory.create().id

        for uni_id in uni_ids:
            model = UniversityIDFactory.create(
                course_key=course_key,
                university_id=uni_id,
                section_number='10',
            )

            model.save()

        marked = UniversityID.get_marked_university_ids(course_key=course_key)

        self.assertEquals(len(marked), len(uni_ids))

        # Should sort the UniversityIDs
        # Should not mark unique IDs
        self.assertListEqual(
            list1=[
                [u'20-01a', False],
                [u'20-02t', False],
                [u'20-03', False],
            ],
            list2=[
                [obj.university_id, obj.is_conflicted]
                for obj in marked[:3]
            ],
        )

        # Should mark conflicted
        self.assertListEqual(
            list1=[
                [u'20-04M\t', True],
                [u'20-04M ', True],
                [u'20-04m', True],
                [u'20-10x', True],
                [u'20-10x ', True],
            ],
            list2=[
                [obj.university_id, obj.is_conflicted]
                for obj in marked[3:]
            ],
        )
