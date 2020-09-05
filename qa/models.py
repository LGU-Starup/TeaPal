from django.db import models
from itertools import chain


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
    identity = models.CharField(max_length=1, null=True, default="V")


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
