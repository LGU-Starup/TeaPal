from django.urls import path

from . import views

urlpatterns = [
    path('api/user/<str:user_name>/', views.get_user_info),
    path('api/user/', views.user_register),
    path('api/user-tag/', views.post_user_tag),
    path('api/email/send/', views.user_send_validate_email),
    path('api/email/validate/', views.user_email_code_validate),
    path('api/reset-psw-email/send/', views.send_reset_password_email),
    path('api/reset-psw-email/validate/', views.validate_reset_password_email),
    path('api/alter-user-info/', views.alter_user_info),
    path('api/login/', views.login),
    path('api/login/resume/', views.resume_login),
    path('api/get_cos_credential/', views.get_cos_credential),
    path('api/chat/', views.post_create_chat),
    path('api/chat/<str:user_name>/', views.get_chat),
    path('api/chat-message/<int:chat_id>/', views.get_chat_message),
    path('api/chat-message/', views.post_chat_message),
    path('api/chat-message/delete/', views.delete_chat_message),
    path('api/friendship/follow/', views.post_follow),
    path('api/friendship/unfollow/', views.post_unfollow),
    path('api/friendship/follower/<str:user_name>/', views.get_follower),
    path('api/friendship/follow/<str:user_name>/', views.get_follow),
    path('api/pair-post/', views.post_pair_degree),
    path('api/pair-initial/<str:user_name>/', views.get_initialize_pair),
    path('api/pair/<str:user_name>/', views.get_pair_degree),
    path('api/moment/', views.post_moment),
    path('api/moment/user/<str:user_name>/<int:page>/', views.get_user_moments),
    path('api/moment/lattest/<int:page>/', views.get_lattest_moments)
]
