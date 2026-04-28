import pytest
from pathlib import Path


@pytest.fixture
def data_dir():
    """Return the project data directory."""
    return Path(__file__).parent.parent / "data"


@pytest.fixture
def demo_papers_path(data_dir):
    """Return the path to the demo papers JSON file."""
    return data_dir / "demo_papers.json"


@pytest.fixture
def research_agent():
    """Create a ResearchAssistant with default demo papers and no LLM enabled."""
    from research_agent.agent import ResearchAssistant

    return ResearchAssistant()


@pytest.fixture
def session_store(tmp_path):
    """Create a SessionStore backed by a temp file so tests are isolated."""
    from research_agent.session_store import SessionStore

    return SessionStore(path=tmp_path / "sessions.json")


@pytest.fixture
def app_service(research_agent, session_store):
    """Create a ResearchApp with a controlled ResearchAssistant and SessionStore."""
    from research_agent.app_service import ResearchApp

    return ResearchApp(agent=research_agent, session_store=session_store)
