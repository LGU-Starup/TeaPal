# Reference: https://django-haystack.readthedocs.io/en/master/views_and_forms.html
#如何实现分页？https://docs.djangoproject.com/zh-hans/3.0/topics/pagination/

from django.http import JsonResponse, HttpResponse
from haystack.views import SearchView
from .models import *
from haystack.query import EmptySearchQuerySet, SearchQuerySet
# from django.core import serializers
# import json

class MySearchView(SearchView):
    """A modified search view (By Xu)"""
    def create_response(self):
        """重载creat_response以对接前端接口"""
        context = super().get_context() #搜索引擎返回的内容
        print(context)
        keyword = self.request.GET.get('q', None) # 从父类调用方法获取关键词 /api/search/?q=
        current_page = self.request.GET.get("page", 1)
        if not keyword:
            return JsonResponse({"status":{"code": 400, "msg": {"error_code": 4450, "error_msg": "invalid keyword!"}}})
        content = {"status": {"code": 200, "msg": 'OK'}, "data": {"page": current_page, "next_page": current_page, "sort": 'default'}} #格式化Json输出
        content_list = [] #储存输出对象
        for i in context['page'].object_list:
            set_dict = {}

            try:
                if i.object.question_id:
                    set_dict = {
                    'id': i.object.question_id,
                    'type': 'Question',
                    'content': i.object.content,
                    }
            except:
                pass
            try:    
                if i.object.anwser_id:
                    set_dict = {
                        'id': i.object.anwser_id,
                        'type': 'Answer',
                        'content': i.object.content,
                    }
            except:
                pass
            try:
                if i.object.comment_id:
                    set_dict = {
                        'id': i.object.comment_id,
                        'type': 'Comment',
                        'content': i.object.content,
                    }
            except:
                pass
            try:
                if i.object.category:
                    set_dict = {
                        'type': 'Handbook',
                        'title': i.object.title,
                        'category': i.object.category,
                        'order': i.object.order,
                        'label': i.object.label,
                        'content': i.object.content,
                    }
            except:
                pass
            try:
                if i.object.post_id:
                    set_dict = {
                        'id': i.object.post_id,
                        'type': 'Post',
                        'title': i.object.title,
                        'content': i.object.content,
                    }
            except:
                pass
            try:
                if i.object.user_name:
                    set_dict = {
                        'type': "User",
                        'name': i.object.user_name,
                        'school_id': i.object.school_id,
                        'school': i.object.school,
                        'college': i.object.college,
                        'avatar': i.object.avatar,
                    }
            except:
                pass
            try:
                if i.object.message_id:
                    set_dict = {
                        'type': 'Message',
                        'question': i.question_id.topic,
                        'content': i.object.content,
                        'created time': i.object.created_time,
                    }
            except:
                pass

            content_list.append(set_dict)
            content["data"].update(dict(result=content_list))
            
        return JsonResponse(content)



