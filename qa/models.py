from django.db import models
from itertools import chain
# reference:
# https://www.zhihu.com/question/38959595

# ForeignKey.on_delete:
# I set all on_delete=SET_NULL to preserve data.
# https://docs.djangoproject.com/zh-hans/3.0/ref/models/fields/#django.db.models.ForeignKey.on_delete
# https://stackoverflow.com/questions/38388423/what-does-on-delete-do-on-django-models

# pretty print in shell
# e.g. User.objects.first()

# param for DateTimeField
# auto_now: 每次保存对象时自动将字段值设置为当前时间
# auto_now_add: 只有第一次保存时才会设置成当前时间


class PrintableModel(models.Model):
    def __repr__(self):
        return str(self.to_dict())

    def to_dict(instance):
        opts = instance._meta
        data = {}
        for f in chain(opts.concrete_fields, opts.private_fields):
            data[f.name] = f.value_from_object(instance)
        for f in opts.many_to_many:
            data[f.name] = [i.id for i in f.value_from_object(instance)]
        return data

    class Meta:
        abstract = True

# Mysql优化： 常用字段放在User表中，不常用的放在User_Info中


class User(PrintableModel):
    user_name = models.CharField(max_length=30, primary_key=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=200)
    created_time = models.DateTimeField(auto_now_add=True)
    token = models.CharField(max_length=100, unique=True)
    expired_date = models.DateTimeField()
    email_code = models.CharField(max_length=10, null=True, default=None)
    is_active = models.BooleanField(default=False)
    avatar = models.CharField(max_length=200, default=None, null=True)

    class Identity(models.TextChoices):
        STUDENT = "S"
        TEACHER = "T"
        VISITOR = "V"
        ADMIN = "A"
    identity = models.CharField(max_length=1, choices=Identity.choices, null=True, default="V")


class User_Info(PrintableModel):
    user_name = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, db_column="user_name", related_name="user_info")
    phone = models.CharField(max_length=30, unique=True, null=True, default=None)
    year = models.IntegerField(null=True, default=None)
    school = models.CharField(max_length=20, default=None, null=True)
    college = models.CharField(max_length=20, default=None, null=True)
    intro = models.CharField(max_length=200, default=None, null=True)
    tag = models.CharField(max_length=500, default=None, null=True)
    school_id = models.IntegerField(unique=True, null=True, default=None)
    follower_cnt = models.PositiveIntegerField(default=0)
    follow_cnt = models.PositiveIntegerField(default=0)

    class Gender(models.TextChoices):
        MAN = 'M'
        WOMAN = 'W'
        UNKNOWN = 'U'
    gender = models.CharField(max_length=1, choices=Gender.choices, null=True, default=None)


class User_Tag(PrintableModel):
    tag_id = models.AutoField(primary_key=True)
    user_name = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_name")
    content = models.CharField(max_length=100, default=None, null=True)


class Question(PrintableModel):
    question_id = models.AutoField(primary_key=True)
    user_name = models.ForeignKey(User, related_name="Question_User_Name", on_delete=models.SET_NULL, null=True, db_column="user_name")
    description = models.CharField(max_length=1000, null=True, default=None)
    topic = models.CharField(max_length=100, null=True, default=None)
    content = models.TextField()
    answer_cnt = models.PositiveIntegerField(default=0)
    updated_time = models.DateTimeField(auto_now=True)
    quote = models.CharField(max_length=200, null=True, default=None)
    quote_cnt = models.PositiveIntegerField(default=0)


class Answer(PrintableModel):
    answer_id = models.AutoField(primary_key=True)
    question_id = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True, db_column="question_id")
    user_name = models.ForeignKey(User, related_name="Answer_User_Name", on_delete=models.SET_NULL, null=True, db_column="user_name")
    content = models.TextField()
    updated_time = models.DateTimeField(auto_now=True)
    comment_cnt = models.PositiveIntegerField(default=0)
    like_cnt = models.PositiveIntegerField(default=0)
    dislike_cnt = models.PositiveIntegerField(default=0)
    quote = models.CharField(max_length=200, null=True, default=None)
    quote_cnt = models.PositiveIntegerField(default=0)


class Comment(PrintableModel):
    comment_id = models.AutoField(primary_key=True)
    answer_id = models.ForeignKey(Answer, on_delete=models.SET_NULL, null=True, db_column="answer_id")
    # reply_comment_id is NULL in default
    reply_comment_id = models.ForeignKey('self', on_delete=models.SET_NULL, default=None, null=True, db_column="reply_comment_id")
    user_name = models.ForeignKey(User, related_name="Comment_User_Name", on_delete=models.SET_NULL, null=True, db_column="user_name")
    content = models.TextField()
    updated_time = models.DateTimeField(auto_now=True)
    count = models.PositiveIntegerField(default=0)
    like_cnt = models.PositiveIntegerField(default=0)
    dislike_cnt = models.PositiveIntegerField(default=0)


class Answer_Vote(PrintableModel):
    answer_vote_id = models.AutoField(primary_key=True)
    user_name = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="user_name")
    answer_id = models.ForeignKey(Answer, on_delete=models.SET_NULL, null=True, db_column="answer_id")

    class Count(models.IntegerChoices):
        LIKE = 1
        NOTHING = 0
        DISLIKE = -1
    count = models.IntegerField(choices=Count.choices, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user_name", "answer_id"], name="unique_answer_vote")]


class Comment_Vote(PrintableModel):
    comment_vote_id = models.AutoField(primary_key=True)
    user_name = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="user_name")
    comment_id = models.ForeignKey(Comment, on_delete=models.SET_NULL, null=True, db_column="comment_id")

    class Count(models.IntegerChoices):
        LIKE = 1
        NOTHING = 0
        DISLIKE = -1
    count = models.IntegerField(choices=Count.choices, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user_name", "comment_id"], name="unique_comment_vote")]


class Post(PrintableModel):
    post_id = models.AutoField(primary_key=True)
    user_name = models.ForeignKey(User, related_name="Post_User_Name", on_delete=models.SET_NULL, null=True, db_column="user_name")
    title = models.CharField(max_length=500)
    content = models.TextField()
    image_url = models.CharField(max_length=500)
    updated_time = models.DateTimeField(auto_now=True)
    comment_cnt = models.PositiveIntegerField(default=0)


# class Comment_Post(PrintableModel):
#     """Comment under a post"""
#     comment_Post.id = models.AutoField(primary_key=True)
#     post = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True, db_column="post_id")
#     user_name = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column='user_name')
#     content = models.TextField('Text', max_length=300)
#     created_time = models.DateTimeField('Create Time', default=now)
#     parent_comment = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, verbose_name='reply')

#     class Meta:


class Message(PrintableModel):
    message_id = models.AutoField(primary_key=True)
    question_id = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True, db_column="question_id", default=None)
    answer_id = models.ForeignKey(Answer, on_delete=models.SET_NULL, null=True, db_column="answer_id", default=None)
    post_id = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True, db_column="post_id", default=None)
    reply_message_id = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, db_column="reply_message_id", default=None)
    content = models.TextField()
    created_time = models.DateTimeField(auto_now_add=True)


class Handbook(PrintableModel):
    handbook_id = models.AutoField(primary_key=True)
    user_name = models.ForeignKey(User, related_name="Handbook_User_Name", on_delete=models.SET_NULL, null=True, db_column="user_name")
    category = models.CharField(max_length=50, default="uncategorized")
    order = models.PositiveIntegerField(default=1)
    handbook_type = models.CharField(max_length=1, null=True, default=None)
    content = models.TextField(null=True, default=None)
    label = models.CharField(max_length=500, null=True, default=None)
    updated_time = models.DateTimeField(auto_now=True)
    title = models.CharField(max_length=200, unique=True, null=True, default=None)
    is_published = models.BooleanField(default=False)
    quote_cnt = models.PositiveIntegerField(default=0)


class Handbook_Draft(PrintableModel):
    draft_id = models.AutoField(primary_key=True)
    user_name = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="user_name", default=None)
    handbook_id = models.OneToOneField(Handbook, on_delete=models.CASCADE, db_column="handbook_id")
    handbook_type = models.CharField(max_length=1, null=True, default=None)
    content = models.TextField(null=True, default=None)
    label = models.CharField(max_length=500, null=True, default=None)
    updated_time = models.DateTimeField(auto_now=True)
    title = models.CharField(max_length=200, null=True, default=None)
    is_published = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)


class Chat(PrintableModel):
    chat_id = models.AutoField(primary_key=True)
    user_a = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="user_a", default=None, related_name="chat_user_a")
    user_b = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="user_b", default=None, related_name="chat_user_b")


class Chat_Message(PrintableModel):
    chat_message_id = models.AutoField(primary_key=True)
    chat_id = models.ForeignKey(Chat, on_delete=models.SET_NULL, null=True, db_column="chat_id", default=None, related_name="chat_message_chat_id")
    from_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="from_user", default=None, related_name="chat_message_from_user")
    to_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="to_user", default=None, related_name="chat_message_to_user")
    created_time = models.DateTimeField(auto_now=True)
    content = models.TextField(null=True, default=None)
    quote = models.CharField(max_length=200, null=True, default=None)
    image = models.CharField(max_length=500, null=True, default=None)


class Last_Message(PrintableModel):
    chat_id = models.OneToOneField(Chat, primary_key=True, on_delete=models.CASCADE, db_column="chat_id", related_name="last_message")
    lattest_message = models.ForeignKey(Chat_Message, on_delete=models.SET_NULL, null=True, default=None, db_column="lattest_message")


class Intimacy(PrintableModel):
    intimacy_id = models.AutoField(primary_key=True)
    user_a = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="user_a", default=None, related_name="intimacy_user_a")
    user_b = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="user_b", default=None, related_name="intimacy_user_b")
    initmacy_mark = models.PositiveIntegerField(default=0)


class Friendship(PrintableModel):
    friendship_id = models.AutoField(primary_key=True)
    follow = models.ForeignKey(User, on_delete=models.CASCADE, null=True, db_column="follower", default=None, related_name="friendship_follower")
    follower = models.ForeignKey(User, on_delete=models.CASCADE, null=True, db_column="followed", default=None, related_name="friendship_followed")
    created_time = models.DateTimeField(auto_now=True)


class Moment(PrintableModel):
    moment_id = models.AutoField(primary_key=True)
    user_name = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_column="user_name", default=None)
    content = models.TextField()
    image = models.CharField(max_length=500, null=True, default=None)
    quote = models.CharField(max_length=200, null=True, default=None)
    created_time = models.DateTimeField(auto_now=True)


class Pair(PrintableModel):
    pair_id = models.AutoField(primary_key=True)
    user_a = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_a", related_name="pair_user_a")
    user_b = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_b", related_name="pair_user_b")
    pair_degree = models.FloatField(default=0)
