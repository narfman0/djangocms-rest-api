# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

from collections import OrderedDict

from classytags.utils import flatten_context
from cms.models import Page, Placeholder, CMSPlugin
from cms.utils.plugins import build_plugin_tree, downcast_plugins
from django.core.urlresolvers import reverse
from rest_framework import serializers
from rest_framework.serializers import ListSerializer
from djangocms_rest_api.serializers.utils import RequestSerializer
from djangocms_rest_api.serializers.mapping import serializer_class_mapping

serializer_cache = {}


class PageSerializer(RequestSerializer, serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    page_title = serializers.SerializerMethodField()
    menu_title = serializers.SerializerMethodField()
    meta_description = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()
    path = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField()
    absolute_url = serializers.SerializerMethodField()
    languages = serializers.ListField(source='get_languages')
    url = serializers.SerializerMethodField()
    redirect = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = [
            'id', 'title', 'placeholders', 'creation_date', 'changed_date', 'publication_date',
            'publication_end_date', 'in_navigation', 'template', 'is_home', 'languages', 'parent',
            'site', 'page_title', 'menu_title', 'meta_description', 'slug', 'url', 'path',
            'absolute_url', 'redirect'
        ]

    def get_title(self, obj):
        return obj.get_title(self.language)

    def get_page_title(self, obj):
        return obj.get_page_title(self.language)

    def get_menu_title(self, obj):
        return obj.get_menu_title(self.language)

    def get_meta_description(self, obj):
        return obj.get_meta_description(self.language)

    def get_slug(self, obj):
        return obj.get_slug(self.language)

    def get_path(self, obj):
        return obj.get_path(self.language)

    def get_template(self, obj):
        return obj.get_template()

    def get_absolute_url(self, obj):
        return obj.get_absolute_url(self.language)

    def get_url(self, obj):
        return reverse('api:page-detail', args=(obj.pk,))

    def get_redirect(self, obj):
        return obj.get_redirect(self.language)

    @classmethod
    def many_init(cls, *args, **kwargs):
        kwargs['child'] = PageSerializer(*args, **kwargs)
        return ListSerializer(*args, **kwargs)


def modelserializer_factory(model, serializer=serializers.ModelSerializer, fields=None, exclude=None, **kwargs):
    """
    Generate serializer basing on django's modelform_factory
    :param model: model we create serializer for
    :param serializer: base serializer class
    :param fields: list of fields to include in serializer
    :param exclude: list of fields to exclude from serializer
    :param kwargs: fields mapping
    :return:
    """

    # TODO: decide if we need cache and what to do with parameters tha can be different
    serializer_class = serializer_cache.get(model, None)

    if serializer_class:
        return serializer_class

    def _get_declared_fields(attrs):
        fields = [(field_name, attrs.pop(field_name))
                  for field_name, obj in list(attrs.items())
                  if isinstance(obj, serializers.Field)]
        fields.sort(key=lambda x: x[1]._creation_counter)
        return OrderedDict(fields)

    meta_attrs = {'model': model}
    if fields is not None:
        meta_attrs['fields'] = fields
    if exclude is not None:
        meta_attrs['exclude'] = exclude

    parent = (object, )
    Meta = type(str('Meta'), parent, meta_attrs)
    class_name = model.__name__ + str('Serializer')

    serializer_class_attrs = {
        'Meta': Meta,
        '_get_declared_fields': _get_declared_fields(kwargs),
    }
    serializer_class = type(serializer)(class_name, (serializer,), serializer_class_attrs)
    serializer_cache[model] = serializer_class
    return serializer_class


# TODO: add custom serializers for base plugins and use them
# TODO: add ability to set custom serializers for plugins
# TODO: Check image plugin data serializer
# TODO: decide if we need to return url for images with domain name or not, cdn?
class BasePluginSerializer(serializers.ModelSerializer):

    plugin_data = serializers.SerializerMethodField()
    inlines = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta:
        model = CMSPlugin
        fields = ['id', 'placeholder', 'parent', 'position', 'language', 'plugin_type', 'creation_date', 'changed_date',
                  'plugin_data', 'inlines', 'children']

    @staticmethod
    def get_serializer(instance, plugin=None, model=None, **kwargs):
        """

        :param instance: model instance or queryset
        :param plugin: plugin instance that is used to get serializer for
        :param model: plugin model we build serializer for
        :param kwargs: kwargs like many and other
        :return:
        """
        assert plugin or model, 'plugin or model should be provided'
        serializer_class = None
        if plugin:
            serializer_class = serializer_class_mapping.get(type(plugin))
        if not serializer_class:
            serializer_class = modelserializer_factory(model)
        if 'read_only' not in kwargs:
            kwargs['read_only'] = True
        return serializer_class(instance, **kwargs)

    def get_plugin_data(self, obj):

        instance, plugin = obj.get_plugin_instance()
        model = getattr(plugin, 'model', None)
        if model:
            serializer = self.get_serializer(instance, model=getattr(plugin, 'model', None), plugin=plugin)
            return serializer.data
        return {}

    def get_inlines(self, obj):
        """
        Some plugin can store data in related models
        This method supposed to fetch data from database for all inline models listed in inlines parameter of plugin
        prepare and return together with parent object
        :param obj:
        :return:
        """
        instance, plugin = obj.get_plugin_instance()
        inlines = getattr(plugin, 'inlines', [])
        data = {}
        for inline in inlines:
            for related_object in instance._meta.related_objects:
                if getattr(related_object, 'related_model', None) == inline.model:
                    name = related_object.name
                    # serializer = modelserializer_factory(inline.model)(getattr(instance, name).all(), many=True)
                    serializer = self.get_serializer(getattr(instance, name).all(), model=inline.model, many=True)
                    data[name] = serializer.data
                    break
        return data

    def get_children(self, obj):
        """
        Some plugins can contain children
        This method supposed to get children and
        prepare and return together with parent object
        :param obj:
        :return:
        """
        data = []
        instance, plugin = obj.get_plugin_instance()
        if not(getattr(plugin, 'allow_children', False) and getattr(plugin, 'child_classes', None)):
            return data
        children = obj.get_descendants().order_by('placeholder', 'path')
        children = [obj] + list(children)
        children = downcast_plugins(children)
        children[0].parent_id = None
        children = build_plugin_tree(children)

        def get_plugin_data(child_plugin):
            # serializer = modelserializer_factory(child_plugin._meta.model)(child_plugin)
            serializer = self.get_serializer(child_plugin, model=child_plugin._meta.model)
            plugin_data = serializer.data
            plugin_data['inlines'] = self.get_inlines(child_plugin)
            if child_plugin.child_plugin_instances:
                plugin_data['children'] = []
                for plug in child_plugin.child_plugin_instances:
                    plugin_data['children'].append(get_plugin_data(plug))
            return plugin_data
        for child in children[0].child_plugin_instances:

            data.append(get_plugin_data(child))
        return data


class SimplePageSerializer(serializers.ModelSerializer):

    class Meta:
        model = Page
        fields = ['id', ]


class PlaceHolderSerializer(RequestSerializer, serializers.ModelSerializer):
    plugins = serializers.SerializerMethodField()
    page = SimplePageSerializer()

    class Meta:
        model = Placeholder
        fields = ['id', 'slot', 'plugins', 'page']
        depth = 2

    def get_plugins(self, obj):
        return [plugin.id for plugin in obj.get_plugins(self.language)]
