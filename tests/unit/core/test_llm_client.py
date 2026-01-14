"""Unit tests for LLM client."""

from unittest.mock import Mock, patch

import pytest

from src.core.config import Settings
from src.core.llm_client import GroqModel, LLMProvider, LLMResponse, UnifiedLLMClient


@pytest.fixture
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Create mock settings with all API keys configured."""
    monkeypatch.setenv("GROQ_API_KEY", "test_groq_key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test_deepseek_key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_anthropic_key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test_google_key")
    monkeypatch.setenv("OPENAI_API_KEY", "test_openai_key")
    return Settings()


@pytest.fixture
def minimal_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Create settings with only OpenAI key."""
    monkeypatch.setenv("OPENAI_API_KEY", "test_openai_key")
    # Clear others by setting to empty string (override .env.local)
    for key in [
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
    ]:
        monkeypatch.setenv(key, "")
    return Settings()


class TestUnifiedLLMClientInit:
    """Test UnifiedLLMClient initialization."""

    def test_init_with_all_keys(self, mock_settings: Settings) -> None:
        """Test initialization with all API keys configured."""
        client = UnifiedLLMClient(settings=mock_settings)

        assert client.groq_client is not None
        assert client.deepseek_client is not None
        assert client.anthropic_client is not None
        assert client.google_client is not None
        assert client.openai_client is not None

    def test_init_with_minimal_keys(self, minimal_settings: Settings) -> None:
        """Test initialization with only required keys."""
        client = UnifiedLLMClient(settings=minimal_settings)

        assert client.groq_client is None
        assert client.deepseek_client is None
        assert client.anthropic_client is None
        assert client.google_client is None
        assert client.openai_client is not None

    def test_pricing_configuration(self, mock_settings: Settings) -> None:
        """Test that pricing is configured for all providers."""
        client = UnifiedLLMClient(settings=mock_settings)

        assert LLMProvider.GROQ in client.pricing
        assert LLMProvider.DEEPSEEK in client.pricing
        assert LLMProvider.ANTHROPIC in client.pricing
        assert LLMProvider.GOOGLE in client.pricing
        assert LLMProvider.OPENAI in client.pricing


class TestCostCalculation:
    """Test cost calculation logic."""

    def test_calculate_cost_groq_8b(self, mock_settings: Settings) -> None:
        """Test cost calculation for Groq 8B model."""
        client = UnifiedLLMClient(settings=mock_settings)

        # 1000 prompt tokens + 500 completion tokens
        cost = client._calculate_cost(
            LLMProvider.GROQ,
            GroqModel.LLAMA_3_8B.value,
            1000,
            500,
        )

        # ($0.05 * 1000/1M) + ($0.08 * 500/1M) = $0.00005 + $0.00004 = $0.00009
        expected = (0.05 * 1000 / 1_000_000) + (0.08 * 500 / 1_000_000)
        assert abs(cost - expected) < 0.000001

    def test_calculate_cost_openai(self, mock_settings: Settings) -> None:
        """Test cost calculation for OpenAI GPT-4."""
        client = UnifiedLLMClient(settings=mock_settings)

        cost = client._calculate_cost(
            LLMProvider.OPENAI,
            "gpt-4o",
            1000,
            500,
        )

        # ($2.50 * 1000/1M) + ($10.00 * 500/1M) = $0.0025 + $0.005 = $0.0075
        expected = (2.50 * 1000 / 1_000_000) + (10.00 * 500 / 1_000_000)
        assert abs(cost - expected) < 0.000001

    def test_calculate_cost_unknown_model(self, mock_settings: Settings) -> None:
        """Test cost calculation for unknown model returns zero."""
        client = UnifiedLLMClient(settings=mock_settings)

        cost = client._calculate_cost(
            LLMProvider.OPENAI,
            "unknown-model",
            1000,
            500,
        )

        assert cost == 0.0


class TestGroqCalls:
    """Test Groq API calls."""

    @patch("openai.OpenAI")
    def test_call_groq_success(
        self,
        mock_openai_class: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test successful Groq API call."""
        # Mock response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Test response"))]
        mock_response.usage = Mock(prompt_tokens=10, completion_tokens=20, total_tokens=30)

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        client = UnifiedLLMClient(settings=mock_settings)
        client.groq_client = mock_client

        response = client._call_groq(
            prompt="Test prompt",
            model=GroqModel.LLAMA_3_8B,
            temperature=0.7,
            max_tokens=100,
            timeout=30,
        )

        assert isinstance(response, LLMResponse)
        assert response.content == "Test response"
        assert response.provider == LLMProvider.GROQ
        assert response.model == GroqModel.LLAMA_3_8B.value
        assert response.prompt_tokens == 10
        assert response.completion_tokens == 20
        assert response.total_tokens == 30
        assert response.cost_usd > 0
        assert response.latency_seconds >= 0

    def test_call_groq_not_configured(self, minimal_settings: Settings) -> None:
        """Test Groq call fails when not configured."""
        client = UnifiedLLMClient(settings=minimal_settings)

        with pytest.raises(ValueError, match="Groq API key not configured"):
            client._call_groq(
                prompt="Test",
                model=GroqModel.LLAMA_3_8B,
                temperature=0.7,
                max_tokens=100,
                timeout=30,
            )


class TestDeepSeekCalls:
    """Test DeepSeek API calls."""

    @patch("openai.OpenAI")
    def test_call_deepseek_success(
        self,
        mock_openai_class: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test successful DeepSeek API call."""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="DeepSeek response"))]
        mock_response.usage = Mock(prompt_tokens=15, completion_tokens=25, total_tokens=40)

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        client = UnifiedLLMClient(settings=mock_settings)
        client.deepseek_client = mock_client

        response = client._call_deepseek(
            prompt="Test prompt",
            temperature=0.7,
            max_tokens=100,
            timeout=30,
        )

        assert response.content == "DeepSeek response"
        assert response.provider == LLMProvider.DEEPSEEK
        assert response.model == "deepseek-chat"
        assert response.prompt_tokens == 15
        assert response.completion_tokens == 25


class TestAnthropicCalls:
    """Test Anthropic Claude API calls."""

    @patch("anthropic.Anthropic")
    def test_call_anthropic_success(
        self,
        mock_anthropic_class: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test successful Anthropic API call."""
        mock_response = Mock()
        mock_response.content = [Mock(text="Claude response")]
        mock_response.usage = Mock(input_tokens=12, output_tokens=18)

        mock_client = Mock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        client = UnifiedLLMClient(settings=mock_settings)
        client.anthropic_client = mock_client

        response = client._call_anthropic(
            prompt="Test prompt",
            temperature=0.7,
            max_tokens=100,
            timeout=30,
        )

        assert response.content == "Claude response"
        assert response.provider == LLMProvider.ANTHROPIC
        assert response.prompt_tokens == 12
        assert response.completion_tokens == 18
        assert response.total_tokens == 30


class TestGoogleCalls:
    """Test Google Gemini API calls."""

    @patch("httpx.Client")
    def test_call_google_success(
        self,
        mock_httpx_class: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test successful Google Gemini API call."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Gemini response"}]},
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 8,
                "candidatesTokenCount": 16,
            },
        }

        mock_client = Mock()
        mock_client.post.return_value = mock_response
        mock_httpx_class.return_value = mock_client

        client = UnifiedLLMClient(settings=mock_settings)
        client.google_client = mock_client

        response = client._call_google(
            prompt="Test prompt",
            temperature=0.7,
            max_tokens=100,
            timeout=30,
        )

        assert response.content == "Gemini response"
        assert response.provider == LLMProvider.GOOGLE
        assert response.prompt_tokens == 8
        assert response.completion_tokens == 16


class TestOpenAICalls:
    """Test OpenAI API calls."""

    @patch("openai.OpenAI")
    def test_call_openai_success(
        self,
        mock_openai_class: Mock,
        mock_settings: Settings,
    ) -> None:
        """Test successful OpenAI API call."""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="GPT-4 response"))]
        mock_response.usage = Mock(prompt_tokens=20, completion_tokens=30, total_tokens=50)

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        client = UnifiedLLMClient(settings=mock_settings)
        client.openai_client = mock_client

        response = client._call_openai(
            prompt="Test prompt",
            temperature=0.7,
            max_tokens=100,
            timeout=30,
        )

        assert response.content == "GPT-4 response"
        assert response.provider == LLMProvider.OPENAI
        assert response.model == "gpt-4o"
        assert response.prompt_tokens == 20
        assert response.completion_tokens == 30


class TestFallbackChain:
    """Test fallback chain logic."""

    def test_generate_uses_groq_first(self, mock_settings: Settings) -> None:
        """Test that generate() tries Groq first when available."""
        client = UnifiedLLMClient(settings=mock_settings)

        # Mock successful Groq call
        mock_response = LLMResponse(
            content="Groq response",
            provider=LLMProvider.GROQ,
            model=GroqModel.LLAMA_3_8B.value,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            cost_usd=0.001,
            latency_seconds=0.5,
        )
        client._call_groq = Mock(return_value=mock_response)

        response = client.generate("Test prompt")

        assert response.provider == LLMProvider.GROQ
        assert response.content == "Groq response"
        client._call_groq.assert_called_once()

    def test_generate_falls_back_to_openai(
        self,
        mock_settings: Settings,
    ) -> None:
        """Test that generate() falls back to OpenAI when Groq fails."""
        client = UnifiedLLMClient(settings=mock_settings)

        # Mock Groq failure
        client._call_groq = Mock(side_effect=Exception("Groq failed"))

        # Mock DeepSeek not configured
        client.deepseek_client = None

        # Mock Anthropic not configured
        client.anthropic_client = None

        # Mock Google not configured
        client.google_client = None

        # Mock successful OpenAI call
        mock_response = LLMResponse(
            content="OpenAI response",
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            cost_usd=0.01,
            latency_seconds=1.0,
        )
        client._call_openai = Mock(return_value=mock_response)

        response = client.generate("Test prompt")

        assert response.provider == LLMProvider.OPENAI
        assert response.content == "OpenAI response"
        assert len(client.errors) == 2  # Two Groq attempts (8B and 70B)

    def test_generate_all_providers_fail(self, mock_settings: Settings) -> None:
        """Test that generate() raises exception when all providers fail."""
        client = UnifiedLLMClient(settings=mock_settings)

        # Mock all providers to fail
        client._call_groq = Mock(side_effect=Exception("Groq failed"))
        client._call_deepseek = Mock(side_effect=Exception("DeepSeek failed"))
        client._call_anthropic = Mock(side_effect=Exception("Anthropic failed"))
        client._call_google = Mock(side_effect=Exception("Google failed"))
        client._call_openai = Mock(side_effect=Exception("OpenAI failed"))

        with pytest.raises(Exception, match="All LLM providers failed"):
            client.generate("Test prompt")

        assert len(client.errors) == 6  # 2 Groq + 4 others

    def test_generate_no_providers_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that generate() fails gracefully with no providers."""
        # Clear all API keys by setting to empty string (override .env.local)
        for key in [
            "GROQ_API_KEY",
            "DEEPSEEK_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
        ]:
            monkeypatch.setenv(key, "")

        settings = Settings()
        client = UnifiedLLMClient(settings=settings)

        with pytest.raises(Exception, match="All LLM providers failed"):
            client.generate("Test prompt")


class TestGenerateParameters:
    """Test generate() parameter handling."""

    def test_generate_uses_default_parameters(
        self,
        mock_settings: Settings,
    ) -> None:
        """Test that generate() uses default parameters from settings."""
        client = UnifiedLLMClient(settings=mock_settings)

        mock_response = LLMResponse(
            content="Test",
            provider=LLMProvider.GROQ,
            model=GroqModel.LLAMA_3_8B.value,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            cost_usd=0.001,
            latency_seconds=0.5,
        )
        client._call_groq = Mock(return_value=mock_response)

        client.generate("Test prompt")

        # Verify defaults were used
        # call_args[0] is positional args: (prompt, model, temperature, max_tokens, timeout)
        call_args = client._call_groq.call_args
        assert call_args[0][2] == mock_settings.default_llm_temperature  # temperature
        assert call_args[0][3] == mock_settings.default_llm_max_tokens  # max_tokens
        assert call_args[0][4] == mock_settings.llm_request_timeout  # timeout

    def test_generate_uses_custom_parameters(
        self,
        mock_settings: Settings,
    ) -> None:
        """Test that generate() accepts custom parameters."""
        client = UnifiedLLMClient(settings=mock_settings)

        mock_response = LLMResponse(
            content="Test",
            provider=LLMProvider.GROQ,
            model=GroqModel.LLAMA_3_8B.value,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            cost_usd=0.001,
            latency_seconds=0.5,
        )
        client._call_groq = Mock(return_value=mock_response)

        client.generate(
            "Test prompt",
            temperature=0.9,
            max_tokens=500,
            timeout=60,
        )

        # Verify custom parameters were used
        # call_args[0] is positional args: (prompt, model, temperature, max_tokens, timeout)
        call_args = client._call_groq.call_args
        assert call_args[0][2] == 0.9  # temperature
        assert call_args[0][3] == 500  # max_tokens
        assert call_args[0][4] == 60  # timeout


class TestErrorTracking:
    """Test error tracking functionality."""

    def test_errors_are_tracked(self, mock_settings: Settings) -> None:
        """Test that errors are tracked in the errors list."""
        client = UnifiedLLMClient(settings=mock_settings)

        # Mock first provider fails, second succeeds
        client._call_groq = Mock(side_effect=Exception("Groq failed"))
        client._call_deepseek = Mock(
            return_value=LLMResponse(
                content="Success",
                provider=LLMProvider.DEEPSEEK,
                model="deepseek-chat",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                cost_usd=0.001,
                latency_seconds=0.5,
            )
        )

        client.generate("Test prompt")

        # Should have 2 errors from Groq attempts (8B and 70B)
        assert len(client.errors) == 2
        assert all(e.provider == LLMProvider.GROQ for e in client.errors)

    def test_errors_cleared_on_new_generate(
        self,
        mock_settings: Settings,
    ) -> None:
        """Test that errors are cleared on each new generate() call."""
        client = UnifiedLLMClient(settings=mock_settings)

        mock_response = LLMResponse(
            content="Test",
            provider=LLMProvider.GROQ,
            model=GroqModel.LLAMA_3_8B.value,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            cost_usd=0.001,
            latency_seconds=0.5,
        )
        client._call_groq = Mock(return_value=mock_response)

        # Add some errors manually
        client.errors = [Mock(), Mock()]

        # Generate should clear errors
        client.generate("Test prompt")

        assert len(client.errors) == 0
