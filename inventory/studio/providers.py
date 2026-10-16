"""
inventory/studio/providers.py
------------------------------
Provider-independent service layer for the JewelDesk AI Jewellery Photo Studio.
Encapsulates Google Gemini GenAI SDK calls, error handling, prompt formulation,
and provides a hermetic mock provider for automated testing and offline dev.
"""

import io
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings
from PIL import Image, ImageDraw, ImageFont


@dataclass
class ProviderResult:
    """Standardized result returned by any photo studio AI provider."""
    success: bool
    image_bytes: Optional[bytes] = None
    mime_type: str = "image/webp"
    error_message: Optional[str] = None
    cost_estimate_usd: float = 0.0
    provider_name: str = "unknown"
    metadata: dict = field(default_factory=dict)


class BasePhotoStudioProvider(ABC):
    """Abstract interface for AI Jewellery Photo Studio image generators."""

    @abstractmethod
    def generate_catalogue_photo(
        self,
        image_bytes: bytes,
        mime_type: str,
        preset_name: str,
        preset_description: str,
        custom_prompt: str = "",
    ) -> ProviderResult:
        """Generate a professional catalogue photo with luxury studio lighting & background."""
        pass

    @abstractmethod
    def generate_model_photo(
        self,
        image_bytes: bytes,
        mime_type: str,
        preset_name: str,
        preset_description: str,
        custom_prompt: str = "",
    ) -> ProviderResult:
        """Generate a realistic photograph of a model wearing the exact uploaded jewellery."""
        pass


class GeminiPhotoStudioProvider(BasePhotoStudioProvider):
    """Google Gemini AI implementation for jewellery catalogue and model imagery."""

    DEFAULT_MODEL = "gemini-2.5-flash-image"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
        self.model_name = (
            model
            or os.environ.get("GEMINI_IMAGE_MODEL")
            or getattr(settings, "GEMINI_IMAGE_MODEL", self.DEFAULT_MODEL)
        ).strip()

    def _is_configured(self) -> bool:
        return bool(self.api_key)

    def _build_catalogue_prompt(self, preset_name: str, preset_description: str, custom_prompt: str) -> str:
        prompt = (
            "You are a master commercial jewellery photographer and digital retoucher.\n"
            "Task: Create a pristine, luxury e-commerce catalogue product photograph featuring the EXACT "
            "piece of jewellery shown in the input image.\n"
            f"Studio Setting & Background: {preset_description}.\n\n"
            "MANDATORY JEWELLERY ACCURACY RULES:\n"
            "1. DO NOT redesign, reshape, or alter the jewellery piece. Preserve exact metal color (yellow gold, "
            "rose gold, white gold, platinum, or silver), gemstone cuts, prong settings, filigree, and proportions.\n"
            "2. The jewellery must be the sharp, crisp focal point of the image with natural studio lighting, "
            "subtle specular highlights on polished metal, and soft realistic contact shadows.\n"
            "3. Clean commercial product look suitable for high-end luxury jewellery catalogues.\n"
        )
        if custom_prompt:
            prompt += f"Special customer styling instructions: {custom_prompt.strip()}\n"
        return prompt

    def _build_model_prompt(self, preset_name: str, preset_description: str, custom_prompt: str) -> str:
        prompt = (
            "You are an editorial high-fashion jewellery photographer.\n"
            "Task: Create a photorealistic editorial photograph of an elegant model wearing the EXACT "
            "piece of jewellery shown in the input image.\n"
            f"Styling & Atmosphere: {preset_description}.\n\n"
            "MANDATORY JEWELLERY ACCURACY RULES:\n"
            "1. The model must wear the EXACT jewellery piece from the input photo without redesigning it, "
            "altering stone colors, changing metal tones, or modifying proportions.\n"
            "2. If the jewellery is a necklace/choker, it must be worn naturally around the neck and collarbone. "
            "If earrings, worn on the earlobe with natural drape. If a ring, worn on an elegant manicured finger. "
            "If bangles/bracelet, worn on the wrist.\n"
            "3. Photorealistic, authentic skin textures, natural posture, and warm flattering luxury lighting.\n"
            "4. The jewellery must remain clearly visible, sharp, and true to the original design.\n"
        )
        if custom_prompt:
            prompt += f"Special customer styling instructions: {custom_prompt.strip()}\n"
        return prompt

    def _call_gemini(self, pil_image: Image.Image, prompt_text: str, is_model: bool) -> ProviderResult:
        if not self._is_configured():
            return ProviderResult(
                success=False,
                error_message=(
                    "Google Gemini API key is not configured. "
                    "Please set the GEMINI_API_KEY environment variable on the server to enable AI Photo Studio."
                ),
                provider_name="gemini",
            )

        start_time = time.time()
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)

            # Generate content using the multimodal image generation/editing endpoint
            response = client.models.generate_content(
                model=self.model_name,
                contents=[pil_image, prompt_text],
            )

            # Parse image from response parts
            output_image_bytes = None
            output_mime = "image/webp"

            # Check response candidates and parts
            parts = getattr(response, "parts", None) or []
            if not parts and getattr(response, "candidates", None):
                candidate = response.candidates[0]
                if getattr(candidate, "content", None) and getattr(candidate.content, "parts", None):
                    parts = candidate.content.parts

            for part in parts:
                # Try as_image() method on Part
                if hasattr(part, "as_image") and callable(part.as_image):
                    try:
                        generated_pil = part.as_image()
                        if generated_pil:
                            buf = io.BytesIO()
                            generated_pil.save(buf, format="WEBP", quality=92)
                            output_image_bytes = buf.getvalue()
                            output_mime = "image/webp"
                            break
                    except Exception:
                        pass

                # Try inline_data attribute
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    raw_data = inline.data
                    if isinstance(raw_data, str):
                        import base64
                        output_image_bytes = base64.b64decode(raw_data)
                    else:
                        output_image_bytes = bytes(raw_data)
                    output_mime = getattr(inline, "mime_type", "image/png") or "image/png"
                    break

            if not output_image_bytes:
                # If text feedback was returned instead of image
                text_feedback = getattr(response, "text", "") or ""
                error_detail = (
                    f"AI did not return an image. Response feedback: {text_feedback[:200]}"
                    if text_feedback
                    else "The AI model did not return image data for this request. Please try another preset or prompt."
                )
                return ProviderResult(
                    success=False,
                    error_message=error_detail,
                    provider_name="gemini",
                )

            duration = round(time.time() - start_time, 2)
            cost_est = 0.067 if is_model else 0.035

            return ProviderResult(
                success=True,
                image_bytes=output_image_bytes,
                mime_type=output_mime,
                cost_estimate_usd=cost_est,
                provider_name="gemini",
                metadata={"duration_seconds": duration, "model": self.model_name},
            )

        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            return ProviderResult(
                success=False,
                error_message=f"Gemini API request failed: {str(exc)}",
                provider_name="gemini",
                metadata={"duration_seconds": duration},
            )

    def generate_catalogue_photo(
        self,
        image_bytes: bytes,
        mime_type: str,
        preset_name: str,
        preset_description: str,
        custom_prompt: str = "",
    ) -> ProviderResult:
        try:
            pil_img = Image.open(io.BytesIO(image_bytes))
            pil_img.load()
        except Exception as exc:
            return ProviderResult(success=False, error_message=f"Invalid source image: {exc}")

        prompt = self._build_catalogue_prompt(preset_name, preset_description, custom_prompt)
        return self._call_gemini(pil_img, prompt, is_model=False)

    def generate_model_photo(
        self,
        image_bytes: bytes,
        mime_type: str,
        preset_name: str,
        preset_description: str,
        custom_prompt: str = "",
    ) -> ProviderResult:
        try:
            pil_img = Image.open(io.BytesIO(image_bytes))
            pil_img.load()
        except Exception as exc:
            return ProviderResult(success=False, error_message=f"Invalid source image: {exc}")

        prompt = self._build_model_prompt(preset_name, preset_description, custom_prompt)
        return self._call_gemini(pil_img, prompt, is_model=True)


class MockPhotoStudioProvider(BasePhotoStudioProvider):
    """Hermetic mock provider for automated unit tests and offline UI development."""

    def _generate_mock_image(self, image_bytes: bytes, title: str, subtitle: str) -> ProviderResult:
        try:
            source = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        except Exception:
            # Fallback canvas if input is mock bytes
            source = Image.new("RGBA", (800, 800), (28, 22, 17, 255))

        # Create output canvas matching luxury atelier style
        canvas_w, canvas_h = 1024, 1024
        canvas = Image.new("RGBA", (canvas_w, canvas_h), (21, 19, 14, 255))

        # Scale source image to fit comfortably in the center
        source.thumbnail((720, 720), Image.Resampling.LANCZOS)
        offset_x = (canvas_w - source.width) // 2
        offset_y = (canvas_h - source.height) // 2 - 30
        canvas.paste(source, (offset_x, offset_y), source if source.mode == "RGBA" else None)

        # Draw luxury watermark banner
        draw = ImageDraw.Draw(canvas)
        # Gold frame border
        draw.rectangle([(20, 20), (canvas_w - 20, canvas_h - 20)], outline=(236, 200, 106, 180), width=2)
        # Title banner
        banner_text = f"JewelDesk AI Studio • {title.upper()}"
        sub_text = f"Preset: {subtitle} | Preserving Original Details"
        draw.rectangle([(30, canvas_h - 90), (canvas_w - 30, canvas_h - 30)], fill=(32, 22, 14, 230))
        draw.text((45, canvas_h - 82), banner_text, fill=(236, 200, 106, 255))
        draw.text((45, canvas_h - 58), sub_text, fill=(212, 197, 176, 255))

        buf = io.BytesIO()
        canvas.convert("RGB").save(buf, format="WEBP", quality=90)
        return ProviderResult(
            success=True,
            image_bytes=buf.getvalue(),
            mime_type="image/webp",
            cost_estimate_usd=0.035,
            provider_name="mock",
            metadata={"mock": True, "title": title, "subtitle": subtitle},
        )

    def generate_catalogue_photo(
        self,
        image_bytes: bytes,
        mime_type: str,
        preset_name: str,
        preset_description: str,
        custom_prompt: str = "",
    ) -> ProviderResult:
        return self._generate_mock_image(image_bytes, "Catalogue Studio", preset_name)

    def generate_model_photo(
        self,
        image_bytes: bytes,
        mime_type: str,
        preset_name: str,
        preset_description: str,
        custom_prompt: str = "",
    ) -> ProviderResult:
        return self._generate_mock_image(image_bytes, "Model Editorial", preset_name)


def get_photo_studio_provider(provider_name: Optional[str] = None) -> BasePhotoStudioProvider:
    """Resolve the active photo studio AI provider.

    Resolution order:
    1. Explicit provider_name == 'mock' or settings.AI_STUDIO_MOCK == True -> MockPhotoStudioProvider
    2. Default -> GeminiPhotoStudioProvider
    """
    is_mock = (
        provider_name == "mock"
        or getattr(settings, "AI_STUDIO_MOCK", False)
        or os.environ.get("AI_STUDIO_MOCK", "").lower() in ("1", "true", "yes")
    )
    if is_mock:
        return MockPhotoStudioProvider()

    return GeminiPhotoStudioProvider()
