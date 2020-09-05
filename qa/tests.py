from django.test import TestCase, Client
from qa.models import *
from django.core import serializers
from django.http import JsonResponse, HttpResponse
# Create your tests here.


class UserTestCase(TestCase):
    def test_get_user_info(self):
        for user in User.objects.all():
            user_id = 10
            response = Client().get('/user/{}'.format(user_id))
            # self.assertIs(response.status_code, 200)
            self.assertIs(200, 300)
