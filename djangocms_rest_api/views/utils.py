# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

from cms.models import Page
from cms.utils.page_permissions import user_can_view_page


class QuerysetMixin(object):

    def get_queryset(self):
        site = get_current_site(self.request)
        queryset = super(QuerysetMixin, self).get_queryset()
        if self.request.user.is_staff:
            return queryset.drafts().on_site(site=site).distinct()
        else:
            return queryset.public().on_site(site=site).distinct()
            

def check_if_page_is_visible(request, page):
    user = request.user
    if page.publisher_is_draft:
        return False

    if page.login_required and not user.is_authenticated():
        return False

    page_is_visible = user_can_view_page(user, page)

    if page_is_visible:
        # Let the cms handle publication dates
        page_is_visible = Page.objects.published().filter(pk=page.pk).exists()
    return page_is_visible
