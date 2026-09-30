"""
accounts/backends.py
--------------------
Authentication backend for JewelDesk supporting sign-in via either
username or email address (case-insensitive).
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticate against either username or email address.
    Supports case-insensitive matching for both identifier types.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD) or kwargs.get('email')

        if username is None or password is None:
            return None

        identifier = str(username).strip()
        if not identifier:
            return None

        try:
            user = (
                UserModel.objects
                .filter(Q(username__iexact=identifier) | Q(email__iexact=identifier))
                .order_by('id')
                .first()
            )
        except Exception:
            return None

        if user is None:
            # Mitigate timing differences by running default hasher once
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
