import re

from django import forms
from django.utils.translation import ugettext_lazy as _

from openedx.core.djangoapps.course_groups.models import CourseUserGroup
from openedx.core.djangoapps.user_api.accounts import NAME_MIN_LENGTH

from models import UniversityID, UniversityIDSettings


class UniversityIDForm(forms.ModelForm):
    full_name = forms.CharField(
        label=_('Full Name in Arabic *'),
        help_text=_('Enter your full name that you use at the university in Arabic.'),
        required=True,
        min_length=NAME_MIN_LENGTH,
        max_length=50,  # Just a basic sanity check
        error_messages={
            'min_length': _('The name you have entered is too short, please double check.'),
            'max_length': _('The student university ID you have entered is too long, please double check.'),
        },
    )

    university_id = forms.RegexField(
        regex=re.compile(r'^[0-9a-z-]+$', re.IGNORECASE),
        label=_('Student University ID *'),
        # TODO: Make ID format instruction course-variant, so coordinators can define it for each course.
        help_text=_('Enter the full student university ID e.g. 201311318.'),
        min_length=4,
        max_length=50,
        error_messages={
            'invalid': _('The student university ID must only consist of numbers, letters and dashes.'),
            'min_length': _('The student university ID you have entered is too short, please double check.'),
            'max_length': _('The student university ID you have entered is too long, please double check.'),
        },
    )

    cohort = forms.ModelChoiceField(
        queryset=CourseUserGroup.objects.none(),
        label=_('Section Number *'),
        # TODO: Make ID format instruction course-variant, so coordinators can define it for each course.
        help_text=_('Select the cohort you are enrolled in.'),
    )

    def __init__(self, course_key, *args, **kwargs):
        super(UniversityIDForm,self).__init__(*args, **kwargs)

        cohorts_choices = CourseUserGroup.objects.filter(course_id=course_key, group_type=CourseUserGroup.COHORT)
        self.fields['cohort'].queryset = cohorts_choices

    class Meta:
        model = UniversityID
        fields = ('full_name', 'university_id', 'cohort')

    def as_div(self):
        """
        Returns this form rendered as HTML <div>s.

        This is similar to Form.as_p() but puts the errors after the field.
        """
        return self._html_output(
            normal_row='<div%(html_class_attr)s>%(label)s %(errors)s %(field)s %(help_text)s</div>',
            error_row='%s',
            row_ender='</div>',
            help_text_html=' <span class="helptext">%s</span>',
            errors_on_separate_row=False,
        )


class UniversityIDSettingsForm(forms.ModelForm):
    class Meta:
        model = UniversityIDSettings
        exclude = ('course_key', )
        widgets = {
            'registration_end_date': forms.TextInput(
                attrs={'placeholder': _('YYYY-MM-DD')}),
        }
