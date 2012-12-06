from corehq.apps.reports.standard import CustomProjectReport
from corehq.apps.reports.generic import GenericTabularReport,\
    SummaryTablularReport
from corehq.apps.reports.datatables import DataTablesHeader, DataTablesColumn
from copy import copy
from corehq.apps.reports.dispatcher import CustomProjectReportDispatcher
import urllib
from dimagi.utils.html import format_html
from corehq.apps.groups.models import Group
from dimagi.utils.decorators.memoized import memoized
from casexml.apps.case.models import CommCareCase
from datetime import datetime, timedelta
from corehq.apps.adm.reports.supervisor import SupervisorReportsADMSection

from django.utils.translation import ugettext_noop
from django.utils.translation import ugettext as _
from bihar.reports.indicators.mixins import IndicatorConfigMixIn

class ConvenientBaseMixIn(object):
    # this is everything that's shared amongst the Bihar supervision reports
    # this class is an amalgamation of random behavior and is just 
    # for convenience

    base_template_mobile = "bihar/base_template_mobile.html"
    report_template_path = "bihar/tabular.html"
    
    hide_filters = True
    flush_layout = True
    mobile_enabled = True
    fields = []
    
    # for the lazy
    _headers = []  # override
    @property
    def headers(self):
        return DataTablesHeader(*(DataTablesColumn(h) for h in self._headers))

    @property
    def render_next(self):
        return None if self.rendered_as == "async" else self.rendered_as
       
    @classmethod
    def show_in_navigation(cls, request, *args, **kwargs):
        return False
     
    @property
    def report_context(self):
        context = super(ConvenientBaseMixIn, self).report_context
        context['home'] = MainNavReport.get_url(self.domain, render_as=self.render_next)
        context['render_as'] = self.render_next
        return context
        
def list_prompt(index, value):
    # e.g. 1. Reports
    return u"%s. %s" % (_(str(index+1)), _(value)) 


class ReportReferenceMixIn(object):
    # allow a report to reference another report
    
    @property
    def next_report_slug(self):
        return self.request_params.get("next_report")
    
    @property
    def next_report_class(self):
        return CustomProjectReportDispatcher().get_report(self.domain, self.next_report_slug)
    

class GroupReferenceMixIn(object):
    # allow a report to reference a group
    
    @property
    def group_id(self):
        return self.request_params["group"]
    
    @property
    @memoized
    def group(self):
        g = Group.get(self.group_id)
        assert g.domain == self.domain, "Group %s isn't in domain %s" % (g.get_id, self.domain)
        return g
    
    @property
    @memoized
    def cases(self):
        return CommCareCase.view('case/by_owner', key=[self.group_id, False],
                                 include_docs=True, reduce=False)

    @property
    @memoized
    def rendered_report_title(self):
        return u"{title} - {group} ({awcc})".format(title=_(self.name),
                                           group=self.group.name,
                                           awcc=get_awcc(self.group))


class BiharSummaryReport(ConvenientBaseMixIn, SummaryTablularReport, 
                         CustomProjectReport):
    # this is literally just a way to do a multiple inheritance without having
    # the same 3 classes extended by a bunch of other classes
    report_template_path = "bihar/summary_tabular.html"
    
            
class BiharNavReport(BiharSummaryReport):
    # this is a bit of a bastardization of the summary report
    # but it is quite DRY
    
    preserve_url_params = False
    
    @property
    def reports(self):
        # override
        raise NotImplementedError("Override this!")
    
    @property
    def _headers(self):
        return [" "] * len(self.reports)
    
    @property
    def data(self):
        return [default_nav_link(self, i, report_cls) for i, report_cls in enumerate(self.reports)]
        
class MockEmptyReport(BiharSummaryReport):
    """
    A stub empty report
    """
    _headers = ["Whoops, this report isn't done! Sorry this is still a prototype."]
    data = [""]
    
        
class SubCenterSelectionReport(ConvenientBaseMixIn, GenericTabularReport, 
                               CustomProjectReport, ReportReferenceMixIn):
    name = ugettext_noop("Select Subcenter")
    slug = "subcenter"
    description = ugettext_noop("Subcenter selection report")
    
    _headers = [ugettext_noop("Team Name"), 
                ugettext_noop("AWCC"),
                # ugettext_noop("Rank")
                ]

    @memoized
    def _get_groups(self):
        if self.request.couch_user.is_commcare_user():
            return Group.by_user(self.request.couch_user)
        else:
            # for web users just show everything?
            return Group.by_domain(self.domain)
        
    @property
    def rows(self):
        return [self._row(g, i+1) for i, g in enumerate(self._get_groups())]
        
    def _row(self, group, rank):
        
        def _link(g):
            params = copy(self.request_params)
            params["group"] = g.get_id
            return format_html(u'<a href="{details}">{group}</a>',
                group=g.name,
                details=url_and_params(self.next_report_class.get_url(self.domain,
                                                                      render_as=self.render_next),
                                       params))
        return [_link(group), get_awcc(group)]
            

class MainNavReport(BiharSummaryReport, IndicatorConfigMixIn):
    name = ugettext_noop("Main Menu")
    slug = "mainnav"
    description = ugettext_noop("Main navigation")

    @classmethod
    def additional_reports(cls):
        return [WorkerRankSelectionReport, ToolsNavReport]
    
    @classmethod
    def show_in_navigation(cls, request, *args, **kwargs):
        return True

    @property
    def _headers(self):
        return [" "] * (len(self.indicator_config.indicator_sets) + len(self.additional_reports())) 

    @property
    def data(self):
        from bihar.reports.indicators.reports import IndicatorNav

        def _indicator_nav_link(i, indicator_set):
            params = copy(self.request_params)
            params["indicators"] = indicator_set.slug
            params["next_report"] = IndicatorNav.slug
            return format_html(u'<a href="{next}">{val}</a>',
                val=list_prompt(i, indicator_set.name),
                next=url_and_params(
                    SubCenterSelectionReport.get_url(self.domain, 
                                                     render_as=self.render_next),
                    params
            ))
        return [_indicator_nav_link(i, iset) for i, iset in\
                enumerate(self.indicator_config.indicator_sets)] + \
               [default_nav_link(self, len(self.indicator_config.indicator_sets) + i, r) \
                for i, r in enumerate(self.additional_reports())]

    
class WorkerRankSelectionReport(SubCenterSelectionReport):
    slug = "workerranks"
    name = ugettext_noop("Worker Rank Table")
    
    def _row(self, group, rank):
        # HACK: hard code this for now until there's an easier 
        # way to get this from configuration
        args = [self.domain, self.render_next] if self.render_next else [self.domain]
        url = SupervisorReportsADMSection.get_url(*args,
                                                  subreport="worker_rank_table")
        end = datetime.today().date()
        start = end - timedelta(days=30)
        params = {
            "ufilter": 0, 
            "startdate": start.strftime("%Y-%m-%d"),
            "enddate": end.strftime("%Y-%m-%d")
        }
        def _link(g):
            params["group"] = g.get_id
            return format_html(u'<a href="{details}">{group}</a>',
                group=g.name,
                details=url_and_params(url,
                                       params))
        return [_link(group)]
    

class DueListReport(MockEmptyReport):
    name = ugettext_noop("Due List")
    slug = "duelist"

class ToolsNavReport(BiharSummaryReport):
    name = ugettext_noop("Tools Menu")
    slug = "tools"
    
    _headers = [" ", " ", " "]

    @property
    def data(self):
        def _referral_link(i):
            params = copy(self.request_params)
            params["next_report"] = ReferralListReport.slug
            return format_html(u'<a href="{next}">{val}</a>',
                val=list_prompt(i, _(ReferralListReport.name)),
                next=url_and_params(
                    SubCenterSelectionReport.get_url(self.domain, 
                                                     render_as=self.render_next),
                    params
            ))
        return [_referral_link(0), 
                default_nav_link(self, 1, EDDCalcReport),
                default_nav_link(self, 2, BMICalcReport),]

class ReferralListReport(GroupReferenceMixIn, MockEmptyReport):
    name = ugettext_noop("Referrals")
    slug = "referrals"

class EDDCalcReport(MockEmptyReport):
    name = ugettext_noop("EDD Calculator")
    slug = "eddcalc"

class BMICalcReport(MockEmptyReport):
    name = ugettext_noop("BMI Calculator")
    slug = "bmicalc"

def default_nav_link(nav_report, i, report_cls):
    url = report_cls.get_url(nav_report.domain, 
                             render_as=nav_report.render_next)
    if getattr(nav_report, 'preserve_url_params', False):
        url = url_and_params(url, nav_report.request_params)
    return format_html(u'<a href="{details}">{val}</a>',
                        val=list_prompt(i, report_cls.name),
                        details=url)

def get_awcc(group):
    return group.metadata.get("awc-code", _('no awc code found'))

def url_and_params(urlbase, params):
    assert "?" not in urlbase
    return "{url}?{params}".format(url=urlbase, 
                                   params=urllib.urlencode(params))