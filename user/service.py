
from user.model import User

def getCurrentUser() -> User:
    return User(id=0, name="Tester", genre_preferences=["pop", "rock"])