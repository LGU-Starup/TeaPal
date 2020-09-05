import datetime
from haystack import indexes
from .models import *

class QuestionIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    #content, user_name
    updated_time = indexes.DateTimeField(model_attr='updated_time')

    def get_model(self):
        return Question

    def index_queryset(self, using=None):
        return self.get_model().objects.filter(updated_time__lte=datetime.datetime.now())

class AnswerIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    #content, user_name
    updated_time = indexes.DateTimeField(model_attr='updated_time')

    def get_model(self):
        return Answer
    
    def index_queryset(self, using=None):
        return self.get_model().objects.filter(updated_time__lte=datetime.datetime.now())

class CommentIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    #content, user_name
    updated_time = indexes.DateTimeField(model_attr='updated_time')

    def get_model(self):
        return Comment

    def index_queryset(self, using=None):
        return self.get_model().objects.filter(updated_time__lte=datetime.datetime.now())

class PostIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    #user_name, content
    updated_time = indexes.DateTimeField(model_attr='updated_time')

    def get_model(self):
        return Post

    def index_queryset(self, using=None):
        return self.get_model().objects.filter(updated_time__lte=datetime.datetime.now())

class HandbookIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    #user_name, content, category, label, title
    updated_time = indexes.DateTimeField(model_attr='updated_time')

    def get_model(self):
        return Handbook

    def index_queryset(self, using=None):
        return self.get_model().objects.filter(updated_time__lte=datetime.datetime.now())

