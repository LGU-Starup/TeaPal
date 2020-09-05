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
        text_content = "This is a validation email, please copy the following code: {} and finish validation\n".format(user.email_code)\
            + "这是一封验证邮件：请复制验证码: {} 完成注册".format(user.email_code)\

        # 组装 HTML 版邮件内容
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open((os.path.join(BASE_DIR, 'email.html')), 'r') as f:
            email_html_str = f.read()
        email_html_str = email_html_str.replace("--code--", user.email_code).replace("--user--", user.user_name)

        send_mail(
            subject="Confirm your email 验证电子邮箱",
            message=text_content,
            from_email="TeaPal <{}>".format(FROM_EMAIL),
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
        text_content = "This is a validation email, please copy the following code: {} and finish validation\n".format(user.email_code)\
            + "这是一封验证邮件：请复制验证码: {} 完成修改".format(user.email_code)\
            # 组装 HTML 版邮件内容
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open((os.path.join(BASE_DIR, 'email-reset-psw.html')), 'r') as f:
            email_html_str = f.read()
        email_html_str = email_html_str.replace("--code--", user.email_code)

        send_mail(
            subject='Reset password 重置您的密码',
            message=text_content,
            from_email="TeaPal <{}>".format(FROM_EMAIL),
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
                    "avatar": user.avatar,
                    "ano_user": ano_user.user_name,
                    "ano_avatar": ano_user.avatar,
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
