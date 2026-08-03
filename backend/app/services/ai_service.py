import json
import logging

from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

METER_READING_PROMPT = """Bạn là chuyên gia phân tích ảnh đồng hồ điện/nước tại Việt Nam.

NHIỆM VỤ: Phân tích ảnh để xác định loại đồng hồ, trích xuất chỉ số VÀ nhận diện số phòng (nếu có ghi trên thân vỏ).

QUY TẮC ĐỌC CHỈ TÀI KHOẢN (meter_reading):
1. Đọc chữ số nguyên chính xác trên mặt đồng hồ (hiển thị kWh hoặc m3).
2. Tùy loại đồng hồ, nếu số cuối cùng màu đỏ hoặc có vạch phân cách, đó là số thập phân -> BỎ QUA phần thập phân đó, CHỈ LẤY phần nguyên.
3. Nếu không chắc chắn, đặt độ tin cậy "confidence" thấp.

QUY TẮC TÌM SỐ PHÒNG (room_number):
1. Nhìn kỹ trên vỏ nhựa hoặc nắp đồng hồ xem có CHỮ VIẾT TAY (bằng bút dạ, bút lông) hoặc DÁN NHÃN KHẮC tay không (VD: "B 1812", "P.101", "205", "1810").
2. TUYỆT ĐỐI BỎ QUA các chữ in sẵn của nhà sản xuất hoặc mã model đồng hồ như "DHN-02", "VIKIDO", "Cấp B", "ISO".
3. Nếu tìm thấy chữ viết tay/nhãn dán số phòng, hãy trích xuất chính xác. Nếu không có, gán null.

QUY TẮC XÁC ĐỊNH LOẠI (meter_type):
1. Chỉ trả "electric" khi ảnh thể hiện rõ đây là đồng hồ điện/kWh.
2. Trả "water" cho đồng hồ nước/m3.
3. Nếu không chắc chắn, trả "unknown"; không được tự suy đoán là điện.

Trả về kết quả dưới định dạng JSON (CHỈ JSON, không giải thích thêm):
{"meter_reading": <số nguyên>, "confidence": <0.0-1.0>, "room_number": "<số phòng nếu có, hoặc null>", "meter_type": "electric|water|unknown", "notes": "<ghi chú>"}
"""


class AIService:
    def get_client(self):
        import os
        from pathlib import Path

        api_key = os.environ.get("GEMINI_API_KEY") or settings.GEMINI_API_KEY
        if not api_key:
            base_dir = Path(__file__).resolve().parent.parent.parent
            for env_p in [base_dir / ".env", Path("backend/.env"), Path(".env")]:
                if env_p.exists():
                    for line in env_p.read_text().splitlines():
                        if line.startswith("GEMINI_API_KEY="):
                            val = line.split("=", 1)[1].strip()
                            if val:
                                api_key = val
                                break
                if api_key:
                    break
        if not api_key or api_key.startswith("your-"):
            return None
        try:
            from google import genai
            return genai.Client(api_key=api_key)
        except Exception:
            logger.warning("Gemini client initialization failed")
            return None

    async def extract_meter_reading(self, image_path: str) -> dict:
        client = self.get_client()
        if not client:
            return {
                "meter_reading": None,
                "confidence": 0.0,
                "room_number": None,
                "meter_type": "unknown",
                "notes": "Chưa cấu hình Gemini API Key (Vào Cài đặt để nhập API Key)",
            }

        try:
            img = Image.open(image_path)

            # Resize if too large
            max_size = 1024
            if max(img.size) > max_size:
                ratio = max_size / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            import asyncio
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.5-flash",
                contents=[METER_READING_PROMPT, img],
            )
            result_text = response.text.strip()

            # Extract JSON from response
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            result = json.loads(result_text)

            # Validate
            if "meter_reading" not in result:
                raise ValueError("Missing meter_reading field")

            result["meter_reading"] = int(result["meter_reading"]) if result["meter_reading"] else None
            result.setdefault("confidence", 0.5)
            result.setdefault("room_number", None)
            meter_type = result.get("meter_type")
            result["meter_type"] = (
                meter_type if meter_type in {"electric", "water", "unknown"} else "unknown"
            )
            result.setdefault("notes", "")

            return result

        except json.JSONDecodeError:
            logger.error("Gemini response was not valid JSON")
            return {
                "meter_reading": None,
                "confidence": 0.0,
                "room_number": None,
                "meter_type": "unknown",
                "notes": "Không thể đọc kết quả AI. Vui lòng kiểm tra ảnh và thử lại.",
            }
        except Exception:
            logger.error("Gemini image processing failed")
            return {
                "meter_reading": None,
                "confidence": 0.0,
                "room_number": None,
                "meter_type": "unknown",
                "notes": "Không thể xử lý ảnh bằng AI. Vui lòng thử lại hoặc kiểm tra cấu hình Gemini.",
            }


def determine_status(confidence: float) -> str:
    """AI confidence is advisory; every extracted reading needs human review."""
    return "needs_review"


ai_service = AIService()
