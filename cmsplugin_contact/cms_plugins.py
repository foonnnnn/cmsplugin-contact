from django import dispatch
from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from django.forms.fields import CharField
from django.core.mail import EmailMessage
from django.template.loader import render_to_string, find_template, TemplateDoesNotExist

from cms.plugin_base import CMSPluginBase
from cms.plugin_pool import plugin_pool
try:
    from cms.plugins.text.settings import USE_TINYMCE
except ImportError:
    USE_TINYMCE = False

from models import Contact
from forms import ContactForm, AkismetContactForm, RecaptchaContactForm, HoneyPotContactForm
from admin import ContactAdminForm


email_sent = dispatch.Signal(providing_args=["data", ])


class ContactPlugin(CMSPluginBase):
    model = Contact
    name = _("Contact Form")
    render_template = "cmsplugin_contact/contact.html"
    form = ContactAdminForm
    contact_form = ContactForm
    subject_template = "cmsplugin_contact/subject.txt"
    email_template = "cmsplugin_contact/email.txt"

    fieldsets = (
        (None, {
            'fields': ('form_name', 'site_email', 'email_label', 'subject_label', 'content_label', 'thanks', 'submit'),
        }),
        (_('Spam Protection'), {
            'fields': ('spam_protection_method', 'akismet_api_key', 'recaptcha_public_key', 'recaptcha_private_key', 'recaptcha_theme')
        })
    )

    change_form_template = "cmsplugin_contact/admin/plugin_change_form.html"

    def get_editor_widget(self, request, plugins):
        """
        Returns the Django form Widget to be used for
        the text area
        """
        if USE_TINYMCE and "tinymce" in settings.INSTALLED_APPS:
            from cms.plugins.text.widgets.tinymce_widget import TinyMCEEditor
            return TinyMCEEditor(installed_plugins=plugins)
        elif "djangocms_text_ckeditor" in settings.INSTALLED_APPS:
            from djangocms_text_ckeditor.widgets import TextEditorWidget
            return TextEditorWidget(installed_plugins=plugins)
        else:
            from cms.plugins.text.widgets.wymeditor_widget import WYMEditor
            return WYMEditor(installed_plugins=plugins)

    def get_form_class(self, request, plugins):
        """
        Returns a subclass of Form to be used by this plugin
        """
        # We avoid mutating the Form declared above by subclassing
        class TextPluginForm(self.form):
            pass
        widget = self.get_editor_widget(request, plugins)

        thanks_field = self.form.base_fields['thanks']

        TextPluginForm.declared_fields["thanks"] = CharField(widget=widget, required=False, label=thanks_field.label, help_text=thanks_field.help_text)
        return TextPluginForm

    def get_form(self, request, obj=None, **kwargs):
        plugins = plugin_pool.get_text_enabled_plugins(self.placeholder, self.page)
        form = self.get_form_class(request, plugins)
        kwargs['form'] = form  # override standard form
        return super(ContactPlugin, self).get_form(request, obj, **kwargs)

    def create_form(self, instance, request):
        if instance.get_spam_protection_method_display() == 'Akismet':
            AkismetContactForm.aksimet_api_key = instance.akismet_api_key
            class ContactForm(self.contact_form, AkismetContactForm):
                pass
            FormClass = ContactForm
        elif instance.get_spam_protection_method_display() == 'ReCAPTCHA':
            #if you really want the user to be able to set the key in
            # every form, this should be more flexible
            class ContactForm(self.contact_form, RecaptchaContactForm):
                recaptcha_public_key = (
                    instance.recaptcha_public_key or
                    getattr(settings, "RECAPTCHA_PUBLIC_KEY", None)
                )
                recaptcha_private_key = (
                    instance.recaptcha_private_key or
                    getattr(settings, "RECAPTCHA_PRIVATE_KEY", None)
                )
                recaptcha_theme = instance.recaptcha_theme

            FormClass = ContactForm
        else:
            class ContactForm(self.contact_form, HoneyPotContactForm):
                pass
            FormClass = ContactForm

        if request.method == "POST":
            return FormClass(request, data=request.POST, files=request.FILES)
        else:
            return FormClass(request)

    def send(self, form, form_name, site_email, attachments=None):
        subject = form.cleaned_data['subject'] if form.cleaned_data['subject'] else _('No subject')
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', form.cleaned_data['email'])
        email_message = EmailMessage(
            render_to_string(self.subject_template, {
                'subject': subject,
                'form_name': form_name,
            }).splitlines()[0],
            render_to_string(self.email_template, {
                'data': form.cleaned_data,
                'form_name': form_name,
                'from_email': from_email,
                'user_email': form.cleaned_data['email'],
            }),
            from_email,
            [site_email],
            headers={'Reply-To': form.cleaned_data['email']},
        )
        if attachments:
            for var_name, data in attachments.iteritems():
                email_message.attach(data.name, data.read(), data.content_type)
        email_message.send(fail_silently=False)
        email_sent.send(sender=self, data=form.cleaned_data)

    def render(self, context, instance, placeholder):
        request = context['request']

        form = self.create_form(instance, request)

        if request.method == "POST" and form.is_valid():
            self.send(form, instance.form_name, instance.site_email, attachments=request.FILES)
            context.update({
                'contact': instance,
            })
        else:
            context.update({
                'contact': instance,
                'form': form,
            })

        return context

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        template = "admin/cms/page/plugin/change_form.html"  # django-cms 3.0
        try:
            find_template(template)
        except TemplateDoesNotExist:
            # django-cms < 3.0
            template = "admin/cms/page/plugin_change_form.html"

        context.update({
            'spam_protection_method': obj.spam_protection_method if obj else 0,
            'recaptcha_settings': hasattr(settings, "RECAPTCHA_PUBLIC_KEY"),
            'akismet_settings': hasattr(settings, "AKISMET_API_KEY"),
            'parent_template': template
        })

        return super(ContactPlugin, self).render_change_form(request, context, add, change, form_url, obj)


plugin_pool.register_plugin(ContactPlugin)
