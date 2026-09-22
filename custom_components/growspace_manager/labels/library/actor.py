"""Who is asking, asked again on every request.

Home Assistant administrators manage the library; any authenticated user may
read what is published and print it. That is two lines of policy, and the
reason it is a module is the third: **a permission is not a lease**. An
administrator who opens the editor and is demoted while it is open keeps their
draft -- the store holds it -- but every further mutation is refused, because
the answer is recomputed from the acting user each time rather than captured
when the editor opened.

An `Actor` is therefore passed into every operation and never cached on the
library. `user_id` is the Home Assistant user the request is attributed to,
and the one drafts belong to: a draft is private to its owner, so the actor is
also the only thing that can name it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.exceptions import Unauthorized

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.auth.models import User

#: The two things an actor can be refused, named so a refusal says which.
#: They are labels on this integration's own policy, not Home Assistant
#: permission keys -- Home Assistant has no per-integration policy to consult.
READ_LIBRARY = "growspace_manager.label_templates.read"
MANAGE_LIBRARY = "growspace_manager.label_templates.manage"


@dataclass(frozen=True, slots=True)
class Actor:
    """One request's authenticated identity and authority."""

    #: The Home Assistant user ID, or `None` for a request with no user
    #: attached. `None` reads nothing and writes nothing: an unattributed
    #: mutation could not own a draft or sign a revision.
    user_id: str | None
    is_admin: bool = False

    @classmethod
    def from_user(cls, user: User | None) -> Actor:
        """Take one Home Assistant user's identity and authority as found."""
        if user is None:
            return cls(user_id=None, is_admin=False)
        return cls(user_id=user.id, is_admin=bool(user.is_admin))

    @property
    def is_authenticated(self) -> bool:
        """Whether this request is attributed to a Home Assistant user."""
        return self.user_id is not None

    def authenticated(self) -> str:
        """Return the acting user ID, refusing an unattributed request."""
        if self.user_id is None:
            raise Unauthorized(permission=READ_LIBRARY)
        return self.user_id

    def administrator(self) -> str:
        """Return the acting admin's user ID, refusing anyone else.

        Called by every mutation, at the moment of the mutation. That is the
        whole of "permission is not a lease".
        """
        user_id = self.authenticated()
        if not self.is_admin:
            raise Unauthorized(user_id=user_id, permission=MANAGE_LIBRARY)
        return user_id
