import collections
from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponse
from .models import *
from django.db.utils import IntegrityError
from django.views.decorators.http import require_http_methods
from django.forms.models import model_to_dict
from itertools import chain
from secrets import token_urlsafe
from datetime import datetime, timedelta
from functools import wraps
from django.db.models import Count, Sum
from django.db.models import Q, F
import json
from django.core.mail import send_mail
from django.views import generic
from django.contrib.auth.mixins import LoginRequiredMixin
from sts.sts import Sts
from qa.cos import client, settings as cos_settings
import os
import re
import copy
import math
from random import sample
from ciwkbe.settings import EMAIL_HOST_USER as FROM_EMAIL
from django.db.models import Max

TOKEN_LENGTH = 50
TOKEN_DURING_DAYS = 15

# predefined HttpResponse
RESPONSE_INVALID_PARAM = HttpResponse(content="Invalid parameter", status=400, reason="I-PAR")
RESPONSE_BLANK_PARAM = HttpResponse(content="Blank or missing required parameter", status=400, reason="B-PAR")

RESPONSE_TOKEN_EXPIRE = HttpResponse(content="Token expire", status=403, reason="T-EXP")
RESPONSE_WRONG_EMAIL_CODE = HttpResponse(content="Wrong email code", status=403, reason="W-EMC")
RESPONSE_AUTH_FAIL = HttpResponse(content="Not Authorized", status=403, reason="N-AUTH")
RESPONSE_EXIST_DEPENDENCY = HttpResponse(content="Exist dependency", status=403, reason="E-DEP")
RESPONSE_UNIQUE_CONSTRAINT = HttpResponse(content="Not satisfy unique constraint", status=403, reason="N-UNI")
RESPONSE_FAIL_SEND_EMAIL = HttpResponse(content="Fail to send email", status=403, reason="E-FTS")
RESPONSE_WRONG_PASSWORD = HttpResponse(content="Wrong password", status=403, reason="W-PWD")

RESPONSE_USER_DO_NOT_EXIST = HttpResponse(content="User do not exist", status=404, reason="U-DNE")
RESPONSE_QUESTION_DO_NOT_EXIST = HttpResponse(content="Question do not exist", status=404, reason="Q-DNE")
RESPONSE_MESSAGE_DO_NOT_EXIST = HttpResponse(content="Message do not exist", status=404, reason="M-DNE")
RESPONSE_ANSWER_DO_NOT_EXIST = HttpResponse(content="Answer do not exist", status=404, reason="A-DNE")
RESPONSE_COMMENT_DO_NOT_EXIST = HttpResponse(content="Comment do not exist", status=404, reason="C-DNE")
RESPONSE_HANDBOOK_DO_NOT_EXIST = HttpResponse(content="Handbook do not exist", status=404, reason="H-DNE")
RESPONSE_DRAFT_DO_NOT_EXIST = HttpResponse(content="Draft do not exist", status=404, reason="D-DNE")
RESPONSE_CHAT_DO_NOT_EXIST = HttpResponse(content="Chat do not exist", status=404, reason="C-DNE")
RESPONSE_CHAT_MSG_DO_NOT_EXIST = HttpResponse(content="Chat message do not exist", status=404, reason="CM-DNE")

RESPONSE_TAG_DO_NOT_EXIST = HttpResponse(content="Tag do not exist", status=404, reason="T-DNE")
RESPONSE_FRIENDSHIP_DO_NOT_EXIST = HttpResponse(content="Friendship do not exist", status=404, reason="F-DNE")

RESPONSE_MOMENT_DO_NOT_EXIST = HttpResponse(content="Moment do not exist", status=404, reason="MO-DNE")


RESPONSE_UNKNOWN_ERROR = HttpResponse(content="Unknown error", status=500, reason="U-ERR")


def post_token_auth_decorator(force_active=True, require_user_identity=["S", "T", "V", "A"]):
    def decorator(func):
        def token_auth(request, *args):
            body_dict = json.loads(request.body.decode('utf-8'))
            try:
                user = User.objects.get(pk=body_dict.get("user_name"))
            except User.DoesNotExist:
                return RESPONSE_USER_DO_NOT_EXIST
            if request.COOKIES.get("token") != user.token:
                return HttpResponse(content="Token does not match user", status=403, reason="T-DNM")
            if user.expired_date < datetime.now():
                return RESPONSE_TOKEN_EXPIRE
            if force_active and not user.is_active:
                return HttpResponse(content="Inactive user, need to validate email", status=403, reason="U-INA")
            if user.identity not in require_user_identity:
                return HttpResponse(content="User wrong identity", status=403, reason="U-WID")
            return func(request, *args)
        return token_auth
    return decorator


def to_dict(instance, except_fields=[]):
    opts = instance._meta
    d = {}
    for f in chain(opts.concrete_fields, opts.private_fields):
        if f.name in except_fields:
            continue
        d[f.name] = f.value_from_object(instance)
    for f in opts.many_to_many:
        if f.name in except_fields:
            continue
        d[f.name] = [i.id for i in f.value_from_object(instance)]
    return d

# User


@require_http_methods(["GET"])
def get_user_info(request, user_name: str):
    try:
        user = User.objects.get(pk=user_name)
        json_dict = {
            **model_to_dict(user, fields=["user_name", "created_time", "is_active", "avatar"]),
            **to_dict(user.user_info)
        }
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
def user_register(request):
    try:
        user = User()
        body_dict = json.loads(request.body.decode('utf-8'))
        user_name = body_dict.get("user_name")
        password = body_dict.get("password")
        email = body_dict.get("email")
        phone = body_dict.get("phone")
        gender = body_dict.get("gender")
        school = body_dict.get("school")
        college = body_dict.get("college")
        intro = body_dict.get("intro")
        avatar = body_dict.get("avatar")
        if not password:
            return RESPONSE_BLANK_PARAM
        if not email:
            return RESPONSE_BLANK_PARAM
        if not user_name:
            return RESPONSE_BLANK_PARAM
        user.user_name = user_name
        user.email = email
        user.password = password
        user.avatar = avatar
        user_info = User_Info(user_name=user)
        user.user_info.phone = phone
        user.user_info.gender = gender
        user.user_info.school = school
        user.user_info.college = college
        user.user_info.intro = intro
        # TODO: regex here?
        email = email.split("@")
        if email[1] == "link.cuhk.edu.cn":
            user.identity = "S"
            user.user_info.school_id = email[0]
            user.user_info.year = int("20"+email[0][1:3])
        elif email[1] == "cuhk.edu.cn":
            user.identity = "T"
        else:
            user.identity = "V"
        user.token = token_urlsafe(TOKEN_LENGTH)
        user.expired_date = datetime.now() + timedelta(days=TOKEN_DURING_DAYS)
        response = HttpResponse(json.dumps({"user_name": user.user_name,
                                            "user_identity": user.identity,
                                            "message": "User register successfully"}),
                                content_type='application/json')
        response.set_cookie("token", user.token)
        user.save()
        user.user_info.save()
        return response
    except IntegrityError:
        return RESPONSE_UNIQUE_CONSTRAINT
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator()
def post_user_tag(request):
    try:
        tag = User_Tag()
        body_dict = json.loads(request.body.decode("utf-8"))
        # user = body_dict.get("user_name")
        content = body_dict.get("content")
        user = User.objects.get(user_name=body_dict.get("user_name"))
        tag.user_name = user
        tag.content = content
        tag.save()
        return HttpResponse("Add tag")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


CODE_LIST = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']


def private_generate_random_code(num_digits=6) -> str:
    return "".join(sample(CODE_LIST, num_digits))


@require_http_methods(["POST"])
def user_send_validate_email(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(pk=body_dict.get("user_name"))
        user.email_code = private_generate_random_code()
        email = body_dict.get("email", user.email)
        if user.email != email:
            user.email = email
            email = email.split("@")
            if email[1] == "link.cuhk.edu.cn":
                user.identity = "S"
                user.user_info.school_id = email[0]
                user.user_info.year = int("20"+email[0][1:3])
            elif email[1] == "cuhk.edu.cn":
                user.identity = "T"
            else:
                user.identity = "V"
        user.is_active = False
        user.save()
        user.user_info.save()
        EMAIL_VERIFY_URL_PREFIX = "http://lguwelcome.online/email-validate/"

        # 组装 Text 版邮件内容
        text_content = "Welcome To LGU (CUHKSZ) Welcome Wall!\n欢迎注册港中深迎新墙账号！\n"\
            + "This is a validation email, please copy the following code: {} and finish validation\n".format(user.email_code)\
            + "这是一封验证邮件：请复制验证码: {} 完成注册".format(user.email_code)\

        # 组装 HTML 版邮件内容
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open((os.path.join(BASE_DIR, 'email.html')), 'r') as f:
            email_html_str = f.read()
        email_html_str = email_html_str.replace("--code--", user.email_code).replace("--user--", user.user_name)

        send_mail(
            subject="Confirm your email 验证电子邮箱",
            message=text_content,
            from_email="LGU Welcome Wall <{}>".format(FROM_EMAIL),
            recipient_list=[user.email],
            fail_silently=False,
            html_message=email_html_str,
        )
        response = HttpResponse("Send email successfully")
        return response
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_FAIL_SEND_EMAIL


@require_http_methods(["POST"])
def user_email_code_validate(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        email_code = body_dict.get("email_code")
        user = User.objects.get(user_name=body_dict.get("user_name"))
        if email_code != user.email_code:
            return RESPONSE_WRONG_EMAIL_CODE
        user.is_active = True
        user.save()
        return HttpResponse(content="Validate email code successfully")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
def send_reset_password_email(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        if body_dict.get("user_name"):
            user = User.objects.get(pk=body_dict.get("user_name"))
        elif body_dict.get("email"):
            user = User.objects.get(email=body_dict.get("email"))

        user.email_code = private_generate_random_code()
        user.save()

        EMAIL_VERIFY_URL_PREFIX = "http://lguwelcome.online/reset-password/"
        link = EMAIL_VERIFY_URL_PREFIX+user.user_name+'/'+user.email_code+'/'

        # 组装 Text 版邮件内容
        text_content = 'You are resetting your LGU Welcome Wall password.\n您正在重设港中迎新墙密码\n\n'\
            + "This is a validation email, please copy the following code: {} and finish validation\n".format(user.email_code)\
            + "这是一封验证邮件：请复制验证码: {} 完成修改".format(user.email_code)\
            # 组装 HTML 版邮件内容
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open((os.path.join(BASE_DIR, 'email-reset-psw.html')), 'r') as f:
            email_html_str = f.read()
        email_html_str = email_html_str.replace("--code--", user.email_code)

        send_mail(
            subject='[LGU Welcome Wall]: Reset password 重置您的密码',
            message=text_content,
            from_email="LGU Welcome Wall <{}>".format(FROM_EMAIL),
            recipient_list=[user.email],
            fail_silently=False,
            html_message=email_html_str,
        )
        response = HttpResponse("Send email successfully")
        return response
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_FAIL_SEND_EMAIL


@require_http_methods(["POST"])
def validate_reset_password_email(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        email_code = body_dict.get("email_code")
        user = User.objects.get(user_name=body_dict.get("user_name"))
        if user.email_code != email_code:
            return RESPONSE_WRONG_EMAIL_CODE
        json_dict = {
            "old_password": user.password,
        }
        response = HttpResponse(json.dumps(json_dict),
                                content_type='application/json')
        response.set_cookie("token", user.token)
        return response
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
def alter_user_info(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(user_name=body_dict.get("user_name"))
        if body_dict.get("password"):
            if body_dict.get("password") != user.password:
                return RESPONSE_WRONG_PASSWORD
            else:
                user.password = body_dict.get("new_password", user.password)
                user.save()
                return JsonResponse({"success": True, "message": "Successfully change password!"})
        else:
            user.user_info.phone = body_dict.get("phone", user.user_info.phone)
            user.user_info.gender = body_dict.get("gender", user.user_info.gender)
            user.user_info.school = body_dict.get("school", user.user_info.school)
            user.user_info.college = body_dict.get("college", user.user_info.college)
            user.user_info.intro = body_dict.get("intro", user.user_info.intro)
            user.avatar = body_dict.get("avatar", user.avatar)
            user.save()
            user.user_info.save()
            return JsonResponse({"user_name": user.user_name,
                                 "message": "Alter user information successfully"})
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except IntegrityError:
        return RESPONSE_UNIQUE_CONSTRAINT
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
def login(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user_name = body_dict.get("user_name")
        email = body_dict.get("email")
        school_id = body_dict.get("school_id")
        if user_name:
            user = User.objects.get(user_name=user_name)
        elif email:
            user = User.objects.get(email=email)
        else:
            user = User.objects.get(school_id=school_id)
        if user.password == body_dict.get("password"):
            user.token = token_urlsafe(TOKEN_LENGTH)
            user.expired_date = datetime.now() + timedelta(days=TOKEN_DURING_DAYS)
            response = HttpResponse(json.dumps({"user_name": user.user_name,
                                                "identity": user.identity,
                                                "message": "login successfully"}),
                                    content_type='application/json')
            response.set_cookie("token", user.token)
            user.save()
            return response
        else:
            return JsonResponse({"user_name": user.user_name,
                                 "identity": user.identity,
                                 "message": "Wrong password"})
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
def resume_login(request):
    try:
        user = User.objects.get(user_name=user_name)
        if user.expired_date < datetime.now():
            return RESPONSE_TOKEN_EXPIRE
        user.token = token_urlsafe(TOKEN_LENGTH)
        user.expired_date = datetime.now() + timedelta(days=TOKEN_DURING_DAYS)
        response = HttpResponse(json.dumps({"user_name": user.user_name,
                                            "message": "resume login successfully"}),
                                content_type='application/json')
        response.set_cookie("token", user.token)
        user.save()
        return response
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# @require_http_methods("GET")
# def user_search(request, query):
#     try:
#         result = User.objects.filter(user_name__icontains=query)
#         json_dict = {}
#         json_dict["result"] = [model_to_dict(u, fields=[
#             "user_name", "gender", "identity", "created_time",
#             "is_active", "year", "school", "college", "intro", "avatar"])
#             for u in result]
#         return JsonResponse(json_dict)
#     except Exception as e:
#         raise e
#         return RESPONSE_UNKNOWN_ERROR

def add_quote_num(quote: dict):
    try:
        url = re.split(r'/', quote.get("url"))
        object_type = quote.get("type")
        if object_type == "handbook":
            category, order = url
            handbook = Handbook.objects.get(category=category, order=order)
            handbook.quote_cnt += 1
            handbook.save()
        if object_type == "question":
            _, question_id = url
            question = Question.objects.get(question_id=question_id)
            question.quote_cnt += 1
            question.save()
        if object_type == "answer":
            _, answer_id = url
            answer = Answer.objects.get(answer_id=answer_id)
            answer.quote_cnt += 1
            answer.save()
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# Question


def private_get_question_brief_answer(question: Question) -> dict:
    answers = Answer.objects.filter(question_id=question).order_by("-like_cnt", "-updated_time")
    if answers.count() == 0:
        return None
    else:
        return model_to_dict(answers[0],
                             fields=["answer_id", "user_name", "content", "updated_time", "comment_cnt", "like_cnt", "dislike_cnt"])


@require_http_methods(["GET"])
# 分页，每页6个
def get_questions_by_pages(request, page, each_page=6):
    try:
        questions = Question.objects.order_by("-updated_time")[(page-1)*each_page:page*each_page]
        json_dict = {}
        json_dict["count"] = Question.objects.count()
        json_dict["current_page"] = page
        json_dict["result"] = [{
            **to_dict(q),
            "brief_answer": private_get_question_brief_answer(q)
        } for q in questions]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator()
def post_question(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user_name = body_dict.get("user_name")
        content = body_dict.get("content")
        quote = body_dict.get("quote")
        if not content:
            return RESPONSE_BLANK_PARAM
        user = User.objects.get(user_name=user_name)
        question = Question(user_name=user, content=content, quote=quote)
        message = Message(question_id=question, content=content)
        question.save(force_insert=True)
        message.save(force_insert=True)
        if quote:
            for quote_dict in quote:
                add_quote_num(quote_dict)
        return HttpResponse(content="post question successfully")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def delete_question(request):
    """Delete a question (By Xu)"""
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(pk=body_dict.get("user_name"))
        question = Question.objects.get(pk=body_dict.get("question_id"))
        message = Message.objects.get(question_id=body_dict.get("question_id"))
        if user != question.user_name and user.identity != "A":
            return RESPONSE_AUTH_FAIL
        if question.answer_cnt > 0 and user.identity != "A":
            return RESPONSE_EXIST_DEPENDENCY
        question.delete()
        message.delete()
        return HttpResponse('Delete question successfully')
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Question.DoesNotExist:
        return RESPONSE_QUESTION_DO_NOT_EXIST
    except Message.DoesNotExist:
        return RESPONSE_MESSAGE_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_question_by_id(request, question_id):
    try:
        q = Question.objects.get(pk=question_id)
        json_dict = {
            **to_dict(q),
            "brief_answer": private_get_question_brief_answer(q)
        }
        return JsonResponse(json_dict)
    except Question.DoesNotExist:
        return RESPONSE_QUESTION_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_hottest_questions(request, each_page=6):
    try:
        hottest_questions = Question.objects.order_by('-answer_cnt')[:each_page]
        json_dict = {}
        json_dict["result"] = [{
            **to_dict(q),
            "user_name": q.user_name.user_name,
            "user_avatar": q.user_name.avatar,
            "brief_answer": private_get_question_brief_answer(q)
        } for q in hottest_questions]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_suggested_questions(request, each_page=6):
    try:
        suggested_questions = Answer.objects.all().values("question_id").annotate(sum_like_cnt=Sum("like_cnt")).order_by("-sum_like_cnt")[:each_page]
        json_dict = {"result": []}
        for each in suggested_questions:
            q = Question.objects.get(pk=each["question_id"])
            json_dict["result"].append({
                **to_dict(q),
                "sum_like_cnt": each["sum_like_cnt"],
                "user_avatar": q.user_name.avatar,
                "brief_answer": private_get_question_brief_answer(q)
            })
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@ require_http_methods(["GET"])
def get_user_questions(request, user_name, page, each_page=6):
    try:
        user_questions = Question.objects.filter(user_name=user_name)
        user = User.objects.get(pk=user_name)
        json_dict = {}
        json_dict["count"] = user_questions.count()
        json_dict["current_page"] = page
        json_dict["user_avatar"] = user.avatar
        result = user_questions.order_by("-updated_time")[(page-1)*each_page:page*each_page]
        json_dict["result"] = [{
            **to_dict(q),
            "user_name": q.user_name.user_name,
            "user_avatar": q.user_name.avatar,
            "brief_answer": private_get_question_brief_answer(q)
        } for q in result]
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# @require_http_methods(["GET"])
# def question_search(request, query):
#     try:
#         result = Question.objects.filter(content__icontains=query)
#         json_dict = {}
#         json_dict["result"] = [to_dict(q) for q in result]
#         return JsonResponse(json_dict)
#     except Exception as e:
#         raise e
#         return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_question_by_topic(request, topic):
    try:
        questions = Question.objects.filter(topic=topic).order_by("-answer_cnt")
        json_dict = {}
        json_dict["results"] = [
            {
                **to_dict(q),
                "brief answer": private_get_question_brief_answer(q)
            } for q in questions
        ]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_question_all_topics(request):
    try:
        topics = Question.objects.filter(~Q(topic="")).values("topic").annotate(count=Count("topic")).order_by("-count")
        json_dict = collections.defaultdict(list)
        for topic in topics:
            topic_dict = dict(topic)
            questions = Question.objects.filter(topic=topic_dict["topic"]).order_by("-answer_cnt", "-updated_time")[:6]
            topic_dict["questions"] = [
                {
                    **to_dict(question, except_fields=["updated_time"]),
                    "answer_hottest": private_get_question_brief_answer(question),
                } for question in questions
            ]
            json_dict["result"].append(topic_dict)
        json_dict = json.loads(json.dumps(json_dict))
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# Answers

@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def post_answer(request):
    def private_user_send_answer_email(user, question):
        subject = "Your question %s got an answer" % question.description
        from_email, to_email = "LGU Welcome Wall <{}>".format(FROM_EMAIL), question.user_name.email
        text_content = "Your question '%s' got an answer\n您的问题: '%s' 收到了回答" % (question.description, question.description)
        question_url = "http://lguwelcome.online/qwall/question/{}/".format(question.question_id)
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open((os.path.join(BASE_DIR, 'email-question-answered.html')), 'r') as f:
            email_html_str = f.read()
        email_html_str = email_html_str.replace("--link--", question_url)
        send_mail(
            subject=subject,
            message=text_content,
            from_email=FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
            html_message=email_html_str,
        )
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        question = Question.objects.get(pk=body_dict.get("question_id"))
        user = User.objects.get(pk=body_dict.get("user_name"))
        reply_message = Message.objects.get(question_id=body_dict.get("question_id"))
        question.answer_cnt += 1
        content = body_dict.get("content")
        quote = body_dict.get("quote")
        answer = Answer(question_id=question, user_name=user, content=content, quote=quote)
        message = Message(answer_id=answer, content=content, reply_message_id=reply_message)
        question.save(force_update=True)
        answer.save()
        message.save(force_insert=True)
        if question.answer_cnt == 1:
            private_user_send_answer_email(user, question)
        if quote:
            for quote_dict in quote:
                add_quote_num(quote_dict)
        return HttpResponse(content="post answer successfully")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Question.DoesNotExist:
        return RESPONSE_QUESTION_DO_NOT_EXIST
    except Message.DoesNotExist:
        return RESPONSE_MESSAGE_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator()
def post_answer_vote(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        answer = Answer.objects.get(pk=body_dict.get("answer_id"))
        user = User.objects.get(pk=body_dict.get("user_name"))
        answer_vote = Answer_Vote.objects.filter(answer_id=answer, user_name=user)
        count = body_dict.get("count")
        if count not in [-1, 0, 1]:
            return RESPONSE_INVALID_PARAM
        if answer_vote:
            # alter vote info
            answer_vote = answer_vote[0]
            if answer_vote.count == count:
                pass
            elif answer_vote.count == 1:
                answer.like_cnt -= 1
                if count == -1:
                    answer.dislike_cnt += 1
            elif answer_vote.count == 0:
                if count == 1:
                    answer.like_cnt += 1
                elif count == -1:
                    answer.dislike_cnt += 1
            elif answer_vote.count == -1:
                answer.dislike_cnt -= 1
                if count == 1:
                    answer.like_cnt += 1
        else:
            # new vote
            answer_vote = Answer_Vote(answer_id=answer, user_name=user, count=count)
            if count == 1:
                answer.like_cnt += 1
            elif count == -1:
                answer.dislike_cnt += 1
        answer_vote.count = count
        answer.save()
        answer_vote.save()
        return HttpResponse(content="vote answer successfully")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Answer.DoesNotExist:
        return RESPONSE_ANSWER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_question_answers(request, question_id):
    try:
        answers = Answer.objects.filter(question_id=question_id).order_by("-like_cnt", "-updated_time")
        json_dict = {}
        json_dict["count"] = answers.count()
        json_dict["result"] = [{
            **to_dict(a),
            "user_name": a.user_name.user_name,
            "user_avatar": a.user_name.avatar,
        }for a in answers]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@ require_http_methods(["GET"])
def get_user_answers(request, user_name):
    try:
        answers = Answer.objects.filter(user_name=user_name).order_by("question_id")
        json_dict = {"result": []}
        question_id, cnt = 0, 0
        for answer in answers:
            if not answer.question_id:
                continue
            if answer.question_id.pk != question_id:
                cnt += 1
                question_id = answer.question_id.pk
                q = Question.objects.get(pk=question_id)
                json_dict["result"].append({**to_dict(q, except_fields=["description", "topic", "answer_cnt", "updated_time"]),
                                            "answers": [],
                                            "user_avatar": q.user_name.avatar})
            json_dict["result"][-1]["answers"].append({**to_dict(answer),
                                                       "user_name": answer.user_name.user_name,
                                                       "user_avatar": answer.user_name.avatar})
        json_dict["count"] = cnt
        return JsonResponse(json_dict)
    except Question.DoesNotExist:
        return RESPONSE_QUESTION_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# @require_http_methods(["GET"])
# def answer_search(request, query):
#     try:
#         result = Answer.objects.filter(content__icontains=query)
#         json_dict = {}
#         json_dict["result"] = [to_dict(a) for a in result]
#         return JsonResponse(json_dict)
#     except Exception as e:
#         raise e
#         return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def delete_answer(request):
    """Delete answer (By Xu)"""
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(pk=body_dict.get("user_name"))
        answer = Answer.objects.get(pk=body_dict.get("answer_id"))
        message = Message.objects.get(answer_id=body_dict.get("answer_id"))
        if user != answer.user_name and user.identity != 'A':
            return RESPONSE_AUTH_FAIL
        if answer.comment_cnt > 0 and user.identity != 'A':
            return RESPONSE_EXIST_DEPENDENCY
        answer.question_id.answer_cnt -= 1
        answer.question_id.save()
        answer.delete()
        message.delete()
        return HttpResponse('Delete answer successfully')
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Answer.DoesNotExist:
        return RESPONSE_ANSWER_DO_NOT_EXIST
    except Message.DoesNotExist:
        return RESPONSE_MESSAGE_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# Comments

@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def post_comment(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(pk=body_dict.get("user_name"))
        answer = Answer.objects.get(pk=body_dict.get("answer_id"))
        answer.comment_cnt += 1
        comment = Comment(user_name=user, answer_id=answer, content=body_dict.get("content"))
        reply_comment_id = body_dict.get("reply_comment_id")
        if reply_comment_id:
            reply_comment = Comment.objects.get(pk=reply_comment_id)
            reply_comment.count += 1
            reply_comment.save(force_update=True)
            comment.reply_comment_id = reply_comment
        answer.save(force_update=True)
        comment.save()
        return HttpResponse(content="post comment successfully")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Answer.DoesNotExist:
        return RESPONSE_ANSWER_DO_NOT_EXIST
    except Comment.DoesNotExist:
        return RESPONSE_COMMENT_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator()
def post_comment_vote(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        comment = Comment.objects.get(pk=body_dict.get("comment_id"))
        user = User.objects.get(pk=body_dict.get("user_name"))
        comment_vote = Comment_Vote.objects.filter(comment_id=comment, user_name=user)
        count = body_dict.get("count")
        if count not in [-1, 0, 1]:
            return RESPONSE_INVALID_PARAM
        if comment_vote:
            # alter vote info
            comment_vote = comment_vote[0]
            if comment_vote.count == count:
                pass
            elif comment_vote.count == 1:
                comment.like_cnt -= 1
                if count == -1:
                    comment.dislike_cnt += 1
            elif comment_vote.count == 0:
                if count == 1:
                    comment.like_cnt += 1
                elif count == -1:
                    comment.dislike_cnt += 1
            elif comment_vote.count == -1:
                comment.dislike_cnt -= 1
                if count == 1:
                    comment.like_cnt += 1
        else:
            # new vote
            comment_vote = Comment_Vote(comment_id=comment, user_name=user, count=count)
            if count == 1:
                comment.like_cnt += 1
            elif count == -1:
                comment.dislike_cnt += 1
        comment_vote.count = count
        comment.save()
        comment_vote.save()
        return HttpResponse(content="vote comment successfully")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Comment.DoesNotExist:
        return RESPONSE_COMMENT_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_answer_comments(request, answer_id, page, each_page=6):
    def private_get_brief_reply_comments(comment: Comment, brief_num=2):
        comment = Comment.objects.filter(reply_comment_id=comment)
        result = []
        while comment:
            new_comment = Comment.objects.none()
            for c in comment:
                result.append({**to_dict(c),
                               "user_name": c.user_name.user_name,
                               "user_avatar": c.user_name.avatar,
                               })
                new_comment.union(new_comment, Comment.objects.filter(reply_comment_id=c))
            if len(result) >= brief_num:
                break
            comment = new_comment
        result = result[:brief_num]
        return result

    try:
        answer = Answer.objects.get(pk=answer_id)
        comments = Comment.objects.filter(answer_id=answer)
        json_dict = {}
        json_dict["count"] = comments.count()
        json_dict["current_page"] = page
        comments = comments.filter(reply_comment_id=None).order_by("updated_time")[(page - 1) * each_page: page * each_page]
        json_dict["result"] = [{
            **to_dict(c),
            "user_name": c.user_name.user_name,
            "user_avatar": c.user_name.avatar,
            "replied_comment": private_get_brief_reply_comments(c),
        } for c in comments]
        return JsonResponse(json_dict)
    except Answer.DoesNotExist:
        return RESPONSE_ANSWER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_all_reply_comments(request, comment_id, page, each_page=6):
    try:
        comment = Comment.objects.get(pk=comment_id)
        comment = Comment.objects.filter(reply_comment_id=comment)
        result = []
        while comment:
            new_comment = Comment.objects.none()
            for c in comment:
                result.append({**to_dict(c),
                               "user_name": c.user_name.user_name,
                               "user_avatar": c.user_name.avatar,
                               })
                new_comment.union(new_comment, Comment.objects.filter(reply_comment_id=c))
            comment = new_comment
        json_dict = {}
        json_dict["count"] = len(result)
        json_dict["result"] = result[(page-1)*each_page:page*each_page]
        return JsonResponse(json_dict)
    except Comment.DoesNotExist:
        return RESPONSE_COMMENT_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_user_comments(request, user_name, page, each_page=6):
    try:
        user = User.objects.get(pk=user_name)
        comments = Comment.objects.filter(user_name=user)
        json_dict = {}
        json_dict["count"] = comments.count()
        json_dict["current_page"] = page
        comments = comments.order_by("-updated_time")[(page - 1) * each_page: page * each_page]
        json_dict["result"] = [{**to_dict(c),
                                "user_name": c.user_name.user_name,
                                "user_avatar": c.user_name.avatar,
                                } for c in comments]
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# Message


def private_get_message_type(message: Message) -> str:
    if message.question_id:
        return "Q"
    elif message.answer_id:
        return "A"
    else:
        return "N"


def private_get_message_user(message: Message) -> User:
    if message.question_id:
        return message.question_id.user_name
    elif message.answer_id:
        return message.answer_id.user_name
    else:
        return message.post_id.user_name


def private_get_reply_message(message: Message) -> dict:
    re_message = message.reply_message_id
    if re_message:
        user = private_get_message_user(re_message)
        quote = re_message.question_id.quote if private_get_message_type(re_message) == "Q" else re_message.answer_id.quote
        return {**model_to_dict(re_message, fields=["message_id", "question_id", "content"]),
                "user_name": user.user_name,
                "user_avatar": user.avatar,
                "type": private_get_message_type(re_message),
                "quote": quote
                }
    else:
        return {}


@ require_http_methods(["GET"])
def get_message_by_page(request, page, num_messages=30):
    # page = 1,2...
    # 按照时间由近到远分组
    try:
        messages = Message.objects.order_by("-created_time")[num_messages*(page-1):num_messages*page]
        json_dict = {}
        json_dict["page"] = page
        json_dict["result"] = [
            {**to_dict(m),
                "user_name": private_get_message_user(m).user_name,
                "user_avatar": private_get_message_user(m).avatar,
                "type": private_get_message_type(m),
                "re": private_get_reply_message(m),
                "quote": m.question_id.quote if private_get_message_type(m) == 'Q' else m.answer_id.quote
             }for m in messages]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@ require_http_methods(["GET"])
def get_lattest_messages(request, num_messages=30):
    return get_message_by_page(request, page=1)


@ require_http_methods(["GET"])
def get_message_by_question_id(request, question_id):
    # 获取某个提问引出的全部回答、追尾等信息
    try:
        question = Question.objects.get(pk=question_id)
        message = Message.objects.get(question_id=question)
        quote = message.question_id.quote if private_get_message_type(message) == "Q" else message.answer_id.quote
        json_dict = {}
        user = private_get_message_user(message)
        json_dict["result"] = [{**to_dict(message),
                                "quote": quote,
                                "user_name": user.user_name,
                                "user_avatar": user.avatar,
                                "type": private_get_message_type(message),
                                "re": private_get_reply_message(message)}]
        cur_message = Message.objects.filter(reply_message_id=message)
        while cur_message:
            nxt_message = []
            for cur_m in cur_message:
                user = private_get_message_user(message)
                quote = cur_m.question_id.quote if private_get_message_type(cur_m) == "Q" else cur_m.answer_id.quote
                json_dict["result"].append({**to_dict(cur_m),
                                            "quote": quote,
                                            "user_name": user.user_name,
                                            "user_avatar": user.avatar,
                                            "quote": quote,
                                            "type": private_get_message_type(cur_m),
                                            "re": private_get_reply_message(cur_m)})
                nxt_message = [nxt_m for nxt_m in Message.objects.filter(reply_message_id=cur_m)]
            cur_message = nxt_message
        return JsonResponse(json_dict)
    except Question.DoesNotExist:
        return RESPONSE_QUESTION_DO_NOT_EXIST
    except Message.DoesNotExist:
        return RESPONSE_MESSAGE_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR

# Handbook


@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def post_create_handbook(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(pk=body_dict.get("user_name"))
        category = body_dict.get("category", "uncategorized")
        if body_dict.get("order"):
            order = body_dict.get("order")
            Handbook.objects.filter(Q(category=category) & Q(order__gte=order)).update(order=F("order")+1)
        else:
            if Handbook.objects.filter(category=category):
                order = Handbook.objects.filter(category=category).aggregate(Max('order'))["order__max"]+1
            # first appeared category
            else:
                order = 1
        handbook = Handbook(user_name=user, category=category, order=order,
                            content=body_dict.get("content"), handbook_type=body_dict.get("handbook_type"),
                            label=body_dict.get("label"), title=body_dict.get("title"),
                            is_published=body_dict.get("is_published", False))
        handbook.save()
        draft = Handbook_draft(user_name=user, handbook_id=handbook,
                               content=body_dict.get("content"), handbook_type=body_dict.get('handbook_type'),
                               label=body_dict.get('label'), title=body_dict.get("title"),
                               is_active=True)
        draft.save()
        json_dict = {"handbook_id": handbook.handbook_id}
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except IntegrityError:
        return RESPONSE_UNIQUE_CONSTRAINT
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def post_alter_handbook(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        if body_dict.get("handbook_id"):
            handbook = Handbook.objects.get(pk=body_dict.get("handbook_id"))
        elif body_dict.get("category") and body_dict.get("order"):
            handbook = Handbook.objects.get(category=body_dict.get("category"), order=body_dict.get("order"))
        else:
            return RESPONSE_BLANK_PARAM
        new_order = body_dict.get("new_order", handbook.order)
        new_category = body_dict.get("new_category", handbook.category)
        if new_category == handbook.category:
            if new_order < handbook.order:
                # [new_order, order-1] += 1
                Handbook.objects.filter(Q(category=new_category) & Q(order__gte=new_order) & Q(order__lte=handbook.order-1)).update(order=F("order")+1)
            elif new_order > handbook.order:
                # [order+1, new_order] -= 1
                Handbook.objects.filter(Q(category=new_category) & Q(order__gte=handbook.order + 1) & Q(order__lte=new_order)).update(order=F("order")-1)
        else:
            # [new_order, end] += 1
            Handbook.objects.filter(Q(category=new_category) & Q(order__gte=new_order)).update(order=F("order") + 1)
        handbook.category = new_category
        handbook.order = new_order
        handbook.content = body_dict.get("content", handbook.content)
        handbook.handbook_type = body_dict.get("handbook_type", handbook.handbook_type)
        handbook.label = body_dict.get("label", handbook.label)
        handbook.title = body_dict.get("title", handbook.title)
        handbook.is_published = body_dict.get("is_published", handbook.is_published)
        handbook.save()
        return HttpResponse(content="Alter handbook successfully")
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except IntegrityError:
        return RESPONSE_UNIQUE_CONSTRAINT
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_handbook_by_category_and_order(request, category, order):
    try:
        handbook = Handbook.objects.get(category=category, order=order)
        if handbook.content:
            new_text = copy.deepcopy(handbook.content)
            code_pattern = re.compile(r'[`].*?[`]', re.S)
            img_pattern = re.compile(r'\!\[.*?\][(].*?[)]', re.S)
            url_pattern = re.compile(r'\!\[.*?\][(](.*?)[)]', re.S)
            alt_pattern = re.compile(r'\![\[](.*?)[\]]\(.*?\)', re.S)
            images = re.findall(img_pattern, code_pattern.sub('', new_text))
            for image in images:
                url = re.findall(url_pattern, image)[0]
                alt = re.findall(alt_pattern, image)[0]
                size = 800
                html = '<div style="display:flex;max-width:100vw;flex-direction:column;align-items:center"><img alt="'+alt+'" width="'+str(size)+'" style="max-width:100%;margin-top:20px" src="'+url+'" /><span style="align-self:center; font-size:16px;">'+alt+'</span></div>'
                new_text = new_text.replace(image, html)
        json_dict = {
            **to_dict(handbook, except_fields=["content", "label"]),
            "label": [l for l in handbook.label.split()] if handbook.label else None,
            "images": re.findall(url_pattern, code_pattern.sub('', handbook.content)) if handbook.content else None,
            "content": new_text if handbook.content else None,
        }
        return JsonResponse(json_dict)
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_handbook_raw_by_category_and_order(request, category, order):
    try:
        handbook = Handbook.objects.get(category=category, order=order)
        if handbook.content:
            new_text = copy.deepcopy(handbook.content)
            code_pattern = re.compile(r'[`].*?[`]', re.S)
            img_pattern = re.compile(r'\!\[.*?\][(].*?[)]', re.S)
            url_pattern = re.compile(r'\!\[.*?\][(](.*?)[)]', re.S)
            alt_pattern = re.compile(r'\![\[](.*?)[\]]\(.*?\)', re.S)
            images = re.findall(img_pattern, code_pattern.sub('', new_text))
        json_dict = {
            **to_dict(handbook, except_fields=["content", "label"]),
            "label": [l for l in handbook.label.split()] if handbook.label else None,
            "images": re.findall(url_pattern, code_pattern.sub('', handbook.content)) if handbook.content else None,
            "content": new_text if handbook.content else None,
        }
        return JsonResponse(json_dict)
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_brief_handbook_by_category_and_order(request, category, order, len_brief_content=100):
    try:
        handbook = Handbook.objects.get(category=category, order=order)
        code_pattern = re.compile(r'[`].*?[`]', re.S)
        replace_pattern = re.compile(r'[(\[.*?\]\((.*?)\))!>#`]')
        img_pattern = re.compile(r'\!\[.*?\][(](.*?)[)]', re.S)
        replace_img_pattern = re.compile(r'\!\[.*?\]\(.*?\)', re.S)
        json_dict = {
            **to_dict(handbook, except_fields=["content", "label"]),
            "label": [l for l in handbook.label.split()] if handbook.label else None,
            "brief_content": replace_pattern.sub('', replace_img_pattern.sub('', handbook.content[:len_brief_content])) if handbook.content else None,
            "images": re.findall(img_pattern, code_pattern.sub('', handbook.content)) if handbook.content else None,
        }
        return JsonResponse(json_dict)
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_handbook_all_categories(request):
    try:
        result = Handbook.objects.filter(~Q(category="uncategorized") & Q(is_published=True)).values("category").annotate(count=Count("category")).order_by("-count")
        json_dict = {}
        json_dict["result"] = [dict(r) for r in result]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_handbooks_by_category(request, category, len_brief_content=50):
    try:
        handbooks = Handbook.objects.filter(Q(category=category) & Q(is_published=True))
        code_pattern = re.compile(r'[`].*?[`]', re.S)
        replace_pattern = re.compile(r'[(\[.*?\]\((.*?)\))!>#`]')
        img_pattern = re.compile(r'\!\[.*?\][(](.*?)[)]', re.S)
        replace_img_pattern = re.compile(r'\!\[.*?\]\(.*?\)', re.S)
        json_dict = {}
        json_dict["count"] = handbooks.count()
        json_dict["result"] = [
            {
                **to_dict(handbook, except_fields=["content", "label"]),
                "label":[l for l in handbook.label.split()] if handbook.label else None,
                "brief_content": replace_pattern.sub('', replace_img_pattern.sub('', handbook.content[:len_brief_content])) if handbook.content else None,
                "images": re.findall(img_pattern, code_pattern.sub('', handbook.content)) if handbook.content else None,
            }
            for handbook in handbooks]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_user_handbooks(request, user_name, len_brief_content=100):
    try:
        result = Handbook.objects.filter(user_name=user_name)
        json_dict = {}
        json_dict["result"] = [{**to_dict(h),
                                "label": [l for l in h.label.split()] if h.label else None,
                                "brief_content": h.content[:len_brief_content] if h.content else None, }
                               for h in result if h.content]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# deprecated
@require_http_methods(["GET"])
def get_all_handbooks(request, len_brief_content=100):
    try:
        result = Handbook.objects.all()
        json_dict = {}
        json_dict["result"] = [{**to_dict(h),
                                "label": [l for l in h.label.split()] if h.label else None,
                                "brief_content": h.content[:len_brief_content] if h.content else None, }
                               for h in result]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# @require_http_methods(["GET"])
# def handbook_search(request, query, field):
#     try:
#         if field == "label":
#             result = Handbook.objects.filter(Q(label__icontains=query) & Q(is_published=True))
#         elif field == "title":
#             result = Handbook.objects.filter(Q(title__icontains=query) & Q(is_published=True))
#         else:
#             result = Handbook.objects.filter(Q(content__icontains=query) & Q(is_published=True))
#         json_dict = {}
#         json_dict["result"] = [to_dict(q) for q in result]
#         return JsonResponse(json_dict)
#     except Exception as e:
#         raise e
#         return RESPONSE_UNKNOWN_ERROR

# TODO： 与post_alter_handbook重复，即将弃用
@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def post_handbook_modify(request):
    """
    Modify the handbook(By Xu):
    Update the title and content of the handbook.
    Get the original handbook via 'Get' method,
    Only the content and content are allowed to change.
    """
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(pk=body_dict.get("user_name"))
        handbook = Handbook.objects.get(category=body_dict.get("category"), order=body_dict.get("order"))

        if user != handbook.user_name and user.identity != 'A':
            return RESPONSE_AUTH_FAIL

        new_title = body_dict.get('new_title')
        new_content = body_dict.get('new_content')
        new_category = body_dict.get('new_category')
        new_status = body_dict.get('new_status')
        new_type = body_dict.get('new_handbook_type')
        new_label = body_dict.get('new_label')

        if not new_title:
            new_title = handbook.title
        if not new_content:
            new_content = handbook.content
        if not new_category:
            new_category = handbook.category
        if not new_status:
            new_category = handbook.is_published
        if not new_type:
            new_type = handbook.handbook_type
        if not new_label:
            new_label = handbook.label

        flag = new_title and new_content and new_category and new_status and new_type and new_label
        # title_repeat = Handbook.objects.filter(title=new_title)
        # if len(title_repeat) > 1:
        #     response = HttpResponse('The title has already existed')
        #     response.status_code = 406
        #     response.reason_phrase = 'T-EXIST'
        #     return response

        # Refresh the database
        handbook.title = new_title
        handbook.content = new_content
        handbook.category = new_category
        handbook.is_published = new_status
        handbook.handbook_type = new_type
        handbook.label = new_label
        handbook.save()
        return HttpResponse('Modify handbook successfully')
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except IntegrityError:
        return RESPONSE_UNIQUE_CONSTRAINT
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def post_handbook_delete(request):
    """Delete a handbook together with its draft (By Xu)"""
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(user_name=body_dict.get("user_name"))
        handbook = Handbook.objects.get(pk=body_dict.get("handbook_id"))
        draft = Handbook_draft.objects.filter(handbook_id=handbook)
        if user.user_name != handbook.user_name.user_name and user.identity != 'A':
            return RESPONSE_AUTH_FAIL
        Handbook.objects.filter(Q(category=handbook.category) & Q(order__gte=handbook.order+1)).update(order=F("order")-1)
        handbook.delete()
        if draft:
            draft.delete()
        return HttpResponse(content="Success! The handbook and its draft has been deleted")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_next_handbook(request, category: str, order: int):
    try:
        handbook = Handbook.objects.get(category=category, order=order)
        nxt_handbook = Handbook.objects.filter(Q(is_published=True) & Q(category=category) & Q(order__gt=order))
        if nxt_handbook.count():
            json_dict = to_dict(nxt_handbook[0])
        else:
            json_dict = {}
        return JsonResponse(json_dict)
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_prev_handbook(request, category: str, order: int):
    try:
        handbook = Handbook.objects.get(category=category, order=order)
        prev_handbook = Handbook.objects.filter(Q(is_published=True) & Q(category=category) & Q(order__lt=order))
        if prev_handbook.count():
            json_dict = to_dict(prev_handbook.last())
        else:
            json_dict = {}
        return JsonResponse(json_dict)
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_newest_handbook(request, number: int):
    """Get the newest n handbooks (By Xu)"""
    try:
        handbook = Handbook.objects.filter(is_published=True).order_by("-updated_time")
        if number <= len(handbook):
            new_handbook = handbook[:number]
        else:
            new_handbook = handbook
        json_dict = {}
        if handbook.count():
            json_dict["result"] = [{**to_dict(h)} for h in new_handbook]
        else:
            json_dict = {"message": 'No available handbooks'}
        return JsonResponse(json_dict)
    except Handbook.DoesNotExist:
        return RESPONSE_ANSWER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR

# @require_http_methods(["GET"])
# def search(request, model, query, field=None):
#     try:
#         if model == "user":
#             return user_search(request, query)
#         elif model == "question":
#             return question_search(request, query)
#         elif model == "answer":
#             return answer_search(request, query)
#         elif model == "handbook":
#             return handbook_search(request, query, field)
#         return RESPONSE_INVALID_PARAM
#     except Exception as e:
#         raise e
#         return RESPONSE_UNKNOWN_ERROR


def get_cos_credential(request):
    """
    Get cos credential.
    By default, the duration is 30 min.
    ---
    Return: json format.
    See https://cloud.tencent.com/document/product/436/31923 
    for more detail.
    """
    config = {
        # 临时密钥有效时长，单位是秒
        'duration_seconds': 7200,
        'secret_id': cos_settings["secret_id"],
        # 固定密钥
        'secret_key': cos_settings["secret_key"],
        # 换成你的 bucket
        'bucket': cos_settings["bucket"],
        # 换成 bucket 所在地区
        'region': cos_settings["region"],
        # 例子： a.jpg 或者 a/* 或者 * (使用通配符*存在重大安全风险, 请谨慎评估使用)
        'allow_prefix': '*',
        # 密钥的权限列表。简单上传和分片需要以下的权限，其他权限列表请看 https://cloud.tencent.com/document/product/436/31923
        'allow_actions': [
            # 简单上传
            'name/cos:PutObject',
            'name/cos:PostObject',
            # 分片上传
            'name/cos:InitiateMultipartUpload',
            'name/cos:ListMultipartUploads',
            'name/cos:ListParts',
            'name/cos:UploadPart',
            'name/cos:CompleteMultipartUpload'
        ],
    }
    try:
        sts = Sts(config)
        response = sts.get_credential()
        # print('get data : ' + json.dumps(dict(response), indent=4))
        return JsonResponse(dict(response))
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# DRAFT

@require_http_methods(["GET"])
def get_draft(request, user_name: str, handbook_id: int):
    """Get the draft of a handbook (By Xu)"""
    try:
        user = User.objects.get(user_name=user_name)
        handbook = Handbook.objects.get(pk=handbook_id)
        draft = Handbook_draft.objects.get(handbook_id=handbook)
        if user.user_name != handbook.user_name.user_name:
            return RESPONSE_AUTH_FAIL
        json_dict = {**to_dict(draft),
                     "label": [l for l in draft.label.split()] if draft.label else None,
                     "category": draft.handbook_id.category,
                     }
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except Draft.DoesNotExist:
        return RESPONSE_DRAFT_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def post_draft_modify(request):
    """编辑过程中，将周期性调用此函数，将原有draft的内容覆盖 (By Xu)"""
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(user_name=body_dict.get("user_name"))
        draft = Handbook_draft.objects.get(handbook_id=body_dict.get("handbook_id"))
        if user.user_name != draft.user_name.user_name:
            return RESPONSE_AUTH_FAIL
        draft.title = body_dict.get('title', draft.title)
        draft.content = body_dict.get('content', draft.content)
        draft.handbook_type = body_dict.get('handbook_type', draft.handbook_type)
        draft.label = body_dict.get('label', draft.label)
        draft.is_active = False
        draft.save()
        return HttpResponse(content='Modify draft successfully')
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Draft.DoesNotExist:
        return RESPONSE_DRAFT_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def post_publish_draft(request):
    """
    用户点击发布，handbook_draft中的字段将同步至handbook中，
    同步后，handbook.is_published = True
    """
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(user_name=body_dict.get("user_name"))
        handbook = Handbook.objects.get(pk=body_dict.get("handbook_id"))
        draft = Handbook_draft.objects.get(handbook_id=handbook)
        if user.user_name != handbook.user_name.user_name:
            return RESPONSE_AUTH_FAIL
        handbook.title = draft.title
        handbook.content = draft.content
        handbook.handbook_type = draft.handbook_type
        handbook.label = draft.label
        handbook.is_published = True
        handbook.save()
        draft.is_active = False
        draft.save()
        return HttpResponse("Publish handbook successfully")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Handbook.DoesNotExist:
        return RESPONSE_HANDBOOK_DO_NOT_EXIST
    except Draft.DoesNotExist:
        return RESPONSE_DRAFT_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator(require_user_identity=["S", "T", "A"])
def post_draft_delete(request):
    """Delete a draft"""
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(user_name=body_dict.get("user_name"))
        draft = Handbook_draft.objects.get(handbook_id=body_dict.get("handbook_id"))
        if user.user_name != draft.user_name.user_name and user.identity != 'A':
            return RESPONSE_AUTH_FAIL
        draft.delete()
        return HttpResponse(content="Success! The draft has been deleted")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Draft.DoesNotExist:
        return RESPONSE_DRAFT_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# Test search by models
@require_http_methods(["GET"])
def search(request, model, query):
    try:
        if model == "user":
            return user_search(request, query)
        elif model == "question":
            return question_search(request, query)
        elif model == "answer":
            return answer_search(request, query)
        elif model == "handbook":
            return handbook_search(request, query)
        elif model == "post":
            return post_search(request, query)
        elif model == "message":
            return message_search(request, query)
        raise Exception("Model not found")
    except Exception as e:
        raise e
        return JsonResponse({"message": e.args})


@require_http_methods("GET")
def user_search(request, query):
    try:
        # result = User.objects.filter(user_name__icontains=query)
        temp, result = [], []
        if User.objects.filter(user_name__icontains=query):
            temp.extend(User.objects.filter(user_name__icontains=query))
        if User.objects.filter(school_id__icontains=query):
            temp.extend(User.objects.filter(school_id__icontains=query))
        if User.objects.filter(school__icontains=query):
            temp.extend(User.objects.filter(school__icontains=query))
        if User.objects.filter(college__icontains=query):
            temp.extend(User.objects.filter(college__icontains=query))
        [result.append(i) for i in temp if i not in result]
        json_dict = {}
        json_dict["type"] = "User"
        json_dict["result"] = [model_to_dict(u, fields=[
            "user_name", "gender", "identity", "created_time",
            "is_active", "year", "school", "college", "intro"])
            for u in result]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return JsonResponse({"message": e.args})


@require_http_methods(["GET"])
def question_search(request, query):
    try:
        # result = Question.objects.filter(content__icontains=query)
        temp, result = [], []
        if Question.objects.filter(content__icontains=query):
            temp.extend(Question.objects.filter(content__icontains=query))
        # if Question.objects.filter(user_name.objects.filter(user_name__icontains=query)):
        #     result.extend(Question.objects.filter(user_name.objects.filter(user_name__icontains=query)))
        if Question.objects.filter(description__icontains=query):
            temp.extend(Question.objects.filter(description__icontains=query))
        if Question.objects.filter(topic__icontains=query):
            temp.extend(Question.objects.filter(topic__icontains=query))
        [result.append(i) for i in temp if i not in result]
        json_dict = {}
        json_dict["type"] = "Question"
        json_dict["result"] = [to_dict(q) for q in result]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return JsonResponse({"message": e.args})


@require_http_methods(["GET"])
def answer_search(request, query):
    try:
        result = Answer.objects.filter(content__icontains=query)
        json_dict = {}
        json_dict["type"] = "answer"
        json_dict["result"] = [to_dict(a) for a in result]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return JsonResponse({"message": e.args})


@require_http_methods(["GET"])
def handbook_search(request, query):
    try:
        # if field == "label":
        #     result = Handbook.objects.filter(Q(label__icontains=query) & Q(is_published=True))
        # elif field == "title":
        #     result = Handbook.objects.filter(Q(title__icontains=query) & Q(is_published=True))
        # else:
        #     result = Handbook.objects.filter(Q(content__icontains=query) & Q(is_published=True))
        temp, result = [], []
        if Handbook.objects.filter(Q(label__icontains=query) & Q(is_published=True)):
            temp.extend(Handbook.objects.filter(Q(label__icontains=query) & Q(is_published=True)))
        if Handbook.objects.filter(Q(category__icontains=query) & Q(is_published=True)):
            temp.extend(Handbook.objects.filter(Q(category__icontains=query) & Q(is_published=True)))
        if Handbook.objects.filter(Q(title__icontains=query) & Q(is_published=True)):
            temp.extend(Handbook.objects.filter(Q(title__icontains=query) & Q(is_published=True)))
        if Handbook.objects.filter(Q(content__icontains=query) & Q(is_published=True)):
            temp.extend(Handbook.objects.filter(Q(content__icontains=query) & Q(is_published=True)))
        [result.append(i) for i in temp if i not in result]
        json_dict = {}
        json_dict["type"] = "Handbook"
        json_dict["result"] = [to_dict(q) for q in result]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return JsonResponse({"message": e.args})


@require_http_methods(["GET"])
def post_search(request, query):
    try:
        temp, result = [], []
        if Post.objects.filter(title__icontains=query):
            temp.extend(Post.objects.filter(title__icontains=query))
        if Post.objects.filter(content__icontains=query):
            temp.extend(Post.objects.filter(content__icontains=query))
        [result.append(i) for i in temp if i not in result]
        json_dict = {}
        json_dict["type"] = "Post"
        json_dict["result"] = [to_dict(q) for q in result]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return JsonResponse(json_dict)


@require_http_methods(['GET'])
def message_search(request, query):
    try:
        result = Message.objects.filter(content__icontains=query)
        json_dict = {}
        json_dict["type"] = "Message"
        json_dict["result"] = [to_dict(q) for q in result]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return JsonResponse({"message": e.args})


@require_http_methods(["GET"])
def tag_search(request, query):
    try:
        result = User_Tag.objects.filter(content__icontains=query)
        json_dict = {}
        json_dict["type"] = "User_Info"
        json_dict["result"] = [to_dict(q) for q in result]
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return JsonResponse({"message": e.args})

# Chat


@require_http_methods(["POST"])
@post_token_auth_decorator()
def post_create_chat(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user_a = User.objects.get(pk=body_dict.get("user_name"))
        user_b = User.objects.get(pk=body_dict.get("to_user_name"))
        chat = Chat.objects.filter((Q(user_a=user_a) & Q(user_b=user_b)) | (Q(user_b=user_a) & Q(user_a=user_b)))
        if not chat:
            chat = Chat(user_a=user_a, user_b=user_b)
            chat.save()
            json_dict = {"chat_id": chat.chat_id}
        else:
            json_dict = {"chat_id": chat[0].chat_id}
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_chat(request, user_name):
    """Get all chat messages of the user"""
    try:
        user = User.objects.get(pk=user_name)
        chats = Chat.objects.filter(Q(user_a=user) | Q(user_b=user))
        json_dict = {
            "count": chats.count(),
            "result": []
        }
        for chat in chats:
            try:
                last_msg = chat.last_message
            except Last_Message.DoesNotExist:
                ano_user = chat.user_a if chat.user_a != user else chat.user_b
                json_dict["result"].append({
                    "chat_id": chat.chat_id,
                    "ano_user": ano_user.user_name,
                    "avatar": ano_user.avatar,
                })
            else:
                if last_msg.lattest_message.from_user == user:
                    ano_user = last_msg.lattest_message.to_user
                else:
                    ano_user = last_msg.lattest_message.from_user
                json_dict["result"].append({
                    "ano_user": ano_user.user_name,
                    "avatar": ano_user.avatar,
                    **to_dict(last_msg.lattest_message, except_fields=["from_user", "to_user"])})
        return JsonResponse(json_dict)
    except Chat.DoesNotExist:
        return RESPONSE_CHAT_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR

# Chat Message


@require_http_methods(["POST"])
@post_token_auth_decorator()
def post_chat_message(request):
    try:
        body_dict = json.loads(request.body.decode("utf-8"))
        from_user = User.objects.get(pk=body_dict.get("user_name"))
        to_user = User.objects.get(pk=body_dict.get("to_user"))
        chat = Chat.objects.get(pk=body_dict.get("chat_id"))
        # chat_message 与 chat 不对应
        if not ((chat.user_a == from_user and chat.user_b == to_user) or (chat.user_b == from_user and chat.user_a == to_user)):
            return RESPONSE_INVALID_PARAM
        content = body_dict.get("content")
        quote = body_dict.get("quote")
        image = body_dict.get("image")
        chat_message = Chat_Message(chat_id=chat, from_user=from_user,
                                    to_user=to_user, content=content, quote=quote, image=image)
        chat_message.save()
        try:
            last_msg = Last_Message.objects.get(chat_id=chat)
        except Last_Message.DoesNotExist:
            last_msg = Last_Message(chat_id=chat, lattest_message=chat_message)
        else:
            last_msg.lattest_message = chat_message
        last_msg.save()
        json_dict = {"chat_message_id:": chat_message.chat_message_id}
        return JsonResponse(json_dict)
    except User.DoesNotExist as e:
        raise e
        return RESPONSE_USER_DO_NOT_EXIST
    except Chat.DoesNotExist:
        return RESPONSE_CHAT_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_chat_message(request, chat_id):
    """Get all chat messages in a chat"""
    try:
        chat = Chat.objects.get(chat_id=chat_id)
        user = User.objects.get(token=request.COOKIES.get("token"))
        # not the 2 users in the given chat
        if chat.user_a != user and chat.user_b != user:
            return RESPONSE_AUTH_FAIL
        chat_msg = Chat_Message.objects.filter(chat_id=chat).order_by("-created_time")
        json_dict = {"count": chat_msg.count()}
        json_dict["result"] = [to_dict(m) for m in chat_msg]
        return JsonResponse(json_dict)
    except Chat.DoesNotExist:
        return RESPONSE_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator()
def delete_chat_message(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        chat_msg = Chat_Message.objects.get(pk=body_dict.get("chat_message_id"))
        # 非用户本人无法删除信息
        if chat_msg.from_user.user_name != body_dict.get("user_name"):
            return RESPONSE_AUTH_FAIL
        chat_msg.delete()
        return HttpResponse(content="Delete chat message successfully")
    except Chat_Message.DoesNotExist:
        return RESPONSE_CHAT_MSG_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR

# Follow


@require_http_methods(["POST"])
@post_token_auth_decorator()
def post_follow(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(user_name=body_dict.get("user_name"))
        user_info = User_Info.objects.get(user_name=user)
        follow_user = User.objects.get(user_name=body_dict.get("follow_user_name"))
        follow_user_info = User_Info.objects.get(user_name=follow_user)
        friendship = Friendship()
        friendship.follow = follow_user
        friendship.follower = user
        user_info.follow_cnt += 1
        follow_user_info.follower_cnt += 1
        friendship.save()
        user_info.save()
        follow_user_info.save()
        return HttpResponse("Followed")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator()
def post_unfollow(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(user_name=body_dict.get("user_name"))
        user_info = User_Info.objects.get(user_name=user)
        follow_user = User.objects.get(user_name=body_dict.get("follow_user_name"))
        follow_user_info = User_Info.objects.get(user_name=follow_user)
        friendship = Friendship.objects.filter(Q(follow=follow_user) & Q(follower=user))
        friendship.delete()
        user_info.follow_cnt -= 1
        follow_user_info.follower_cnt -= 1
        user_info.save()
        follow_user_info.save()
        return HttpResponse("Unfollowed")
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_follower(request, user_name):
    try:
        user = User.objects.get(user_name=user_name)
        user_info = User_Info.objects.get(user_name=user)
        friendships = Friendship.objects.filter(follow=user).order_by("-created_time")
        json_dict = {"total_follower": user_info.follower_cnt}
        json_dict["result"] = [
            {
                **to_dict(f.follower.user_info),
                "avatar": f.follower.avatar
            } for f in friendships
        ]
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_follow(request, user_name):
    try:
        user = User.objects.get(user_name=user_name)
        user_info = User_Info.objects.get(user_name=user)
        friendships = Friendship.objects.filter(follower=user).order_by("-created_time")
        json_dict = {"total_follow": user_info.follow_cnt}
        json_dict["result"] = [
            {
                **to_dict(f.follow.user_info),
                "avatar": f.follow.avatar
            } for f in friendships
        ]
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


# Pair

@require_http_methods(["GET"])
def get_initialize_pair(request, user_name):
    """在用户刚刚创建账号时推荐用户根据标签的重合度
        返回三个，根据follower的数量返回三个"""
    try:
        user = User.objects.get(pk=user_name)
        tags = User_Tag.objects.filter(user_name=user)
        user_repeat, json_dict = {}, {}
        result = []
        for tag in tags:
            repeat_tag = User_Tag.objects.filter(content__icontains=tag)
            for t in repeat_tag:
                user_repeat[t.user_name] = user_repeat.get(t.user_name) + 1
        user_repeat = sorted(user_repeat.items(), key=lambda item: item[1])[-3:]
        popular_user = User_Info.objects.all().order_by('-follower_cnt')[:3]
        L = [
            {
                **to_dict(p)
            } for p in popular_user
        ]
        for i, _ in user_repeat:
            user_info = User_Info.objects.get(user_name=i)
            json_dict["result"].append({
                **to_dict(user_info),
            })
        result = [i for i in L if i not in result]
        json_dict["result"] = result
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


def calc_total_friends(user):
    try:
        friendship = Friendship.objects.filter(follower=user)
        return friendship.count()
    except Friendship.DoesNotExist:
        return 0


def calc_common_friends(friendships, p_friendships):
    interact_friends = [f for f in friendships if f in p_friendships]
    union_friends = list(set(friendships).union(set(p_friendships)))
    N = len(interact_friends)
    w_jaccord = float(N/len(union_friends))
    w_common_friends = [float(1/math.log2(i)) for f in interact_friends]
    w_common_friends = sum(w_common_friends)
    return float(w_common_friends * (len(interact_friends)/len(union_friends)))


# def calc_tag_appearances(tag, moment):
#     return moment.content.count(tag.content.count())

# def calc_common_interest(repeated_tags, moments):
#     for tag in repeated_tags:


def calc_pair_degree(user, p, friendships, tags):
    """计算匹配度，用杰卡比相似系数与共同好友的好友数对共同好友数加权"""
    try:
        # p_moment = Moment.objects.get(user_name=p)
        p_tags = User_Tag.objects.filter(user_name=p)
        # repeated_tags = [i for i in tags if i in p_tags]
        p_friendships = Friendship.objects.filter(follower=p)
        pair_degree = calc_common_friends(friendships, p_friendships)
        pair = Pair()
        pair.user_a = user
        pair.user_b = p
        pair.pair_degree = pair_degree
        pair.save()
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["POST"])
@post_token_auth_decorator()
def post_pair_degree(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(user_name=body_dict.get("user_name"))
        tags = User_Tag.objects.filter(user_name=user)
        # moments = Moment.objects.get(user_name=user)
        friendships = Friendship.objects.filter(follower=user)
        pair_user = User.objects.filter(~Q(user_name=body_dict.get("user_name")))
        for p in pair_user:
            calc_pair_degree(user, p, friendships, tags)
        return HttpResponse("Pair_degree has been updated")
    except User.DoesNotExist:
        return RESPONSE_DO_NOT_EXIST
    except User_Tag.DoesNotExist:
        return RESPONSE_TAG_DO_NOT_EXIST
    except Friendship.DoesNotExist:
        return RESPONSE_FRIENDSHIP_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_pair_degree(request, user_name):
    try:
        user = User.objects.get(user_name=user_name)
        pairs = Pair.objects.filter(Q(user_a=user) | Q(user_b=user)).order_by("-pair_degree")[:4]
        popular_user = User_Info.objects.filter(~Q(user_name=user_name)).order_by("-follower_cnt")[:2]
        json_dict = dict(result=[])
        for p in pairs:
            if p.user_a != user:
                p_user_info = User_Info.objects.get(user_name=p.user_a)
                json_dict["result"].append(
                    model_to_dict(p_user_info)
                )
            else:
                p_user_info = User_Info.objects.get(user_name=p.user_b)
                json_dict["result"].append(
                    model_to_dict(p_user_info)
                )
        json_dict["result"].append([{
            **to_dict(u)
        } for u in popular_user])
        return JsonResponse(json_dict)
    except Pair.DoesNotExist:
        get_initialize_pair(request, user_name)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR

# Moment


@require_http_methods(["POST"])
def post_moment(request):
    try:
        body_dict = json.loads(request.body.decode('utf-8'))
        user = User.objects.get(pk=body_dict.get("user_name"))
        moment = Moment(user_name=user, content=body_dict.get("content"),
                        image=body_dict.get("image"), quote=body_dict.get("quote"))
        moment.save()
        json_dict = {"moment_id": moment.moment_id}
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_user_moments(request, user_name: str, page=1, per_page=6):
    try:
        user = User.objects.get(pk=user_name)
        moments = Moment.objects.filter(user_name=user).order_by("-created_time")
        json_dict = {
            "count": moments.count(),
            "current_page": page,
            "result": [],
        }
        moments = moments[per_page*(page-1):per_page*page]
        for moment in moments:
            json_dict["result"].append(to_dict(moment))
        return JsonResponse(json_dict)
    except User.DoesNotExist:
        return RESPONSE_USER_DO_NOT_EXIST
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR


@require_http_methods(["GET"])
def get_lattest_moments(request, page=1, per_page=6):
    try:
        moments = Moment.objects.all().order_by("-created_time")
        json_dict = {
            "count": moments.count(),
            "current_page": page,
            "result": [],
        }
        moments = moments[per_page*(page-1):per_page*page]
        for moment in moments:
            json_dict["result"].append(to_dict(moment))
        return JsonResponse(json_dict)
    except Exception as e:
        raise e
        return RESPONSE_UNKNOWN_ERROR
