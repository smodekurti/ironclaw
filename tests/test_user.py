import pytest
import os
import tempfile
from ironclaw.user.profile import UserProfile
from ironclaw.user.store import UserStore

def test_user_store():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name
        
    store = UserStore(path)
    store.clear()
    
    prof = UserProfile(name="John", about="Developer")
    store.save(prof)
    
    assert store.exists() == True
    
    loaded = store.load()
    assert loaded.name == "John"
    
    store.update(name="Jane")
    loaded2 = store.load()
    assert loaded2.name == "Jane"
    
    store.add_do("test_do")
    store.add_dont("test_dont")
    
    loaded3 = store.load()
    assert "test_do" in loaded3.dos
    assert "test_dont" in loaded3.donts
    
    store.remove_do("test_do")
    store.remove_dont("test_dont")
    
    loaded4 = store.load()
    assert "test_do" not in loaded4.dos
    assert "test_dont" not in loaded4.donts
    
    os.remove(path)
