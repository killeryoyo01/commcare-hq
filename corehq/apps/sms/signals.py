from casexml.apps.case.signals import case_post_save
from casexml.apps.case.models import CommCareCase
from corehq.form_processor.signals import sql_case_post_save
from corehq.form_processor.models import CommCareCaseSQL
from dimagi.utils.logging import notify_exception


def case_changed_receiver(sender, case, **kwargs):
    try:
        from corehq.apps.sms.tasks import sync_case_phone_number
        sync_case_phone_number.delay(case)
    except Exception:
        notify_exception(
            None,
            message="Could not create sync_case_phone_number task for case %s" % case.case_id
        )


case_post_save.connect(case_changed_receiver, CommCareCase)
sql_case_post_save.connect(case_changed_receiver, CommCareCaseSQL)
