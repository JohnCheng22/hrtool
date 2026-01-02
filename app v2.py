import os
import streamlit as st
import pandas as pd
import PyPDF2
import pdfplumber

# Optional: google genai (Gemini). Import lazily to avoid startup error when key not set.
try:
    import google.genai as genai
    _HAS_GENAI = True
except Exception:
    _HAS_GENAI = False

st.set_page_config(page_title="公司新人 Onboarding 工具", layout="wide")

# Configure Gemini API key from environment variable
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 
if GEMINI_API_KEY:
    if _HAS_GENAI:
        try:
            # Newer `google.genai` exposes a Client class. Prefer creating a client
            # with the API key and attach it to the module for compatibility.
            if hasattr(genai, 'Client'):
                genai_client = genai.Client(api_key=GEMINI_API_KEY)
                try:
                    genai.client = genai_client
                except Exception:
                    pass
            # Fallback to configure if present (older API surface)
            elif hasattr(genai, 'configure'):
                genai.configure(api_key=GEMINI_API_KEY)
            else:
                raise RuntimeError('no supported genai configuration API found')
        except Exception as e:
            st.warning(f"無法設定 Gemini API：{e}")

# PWA / mobile hint (works when deployed as a static site or with proper manifest)
st.markdown("""
<link rel="manifest" href="data:application/manifest+json,{
  'name': 'HR Onboarding Tool',
  'short_name': 'Onboarding',
  'start_url': '.',
  'display': 'standalone',
  'background_color': '#ffffff',
  'theme_color': '#007bff',
  'icons': [{'src': 'https://via.placeholder.com/192', 'sizes': '192x192', 'type': 'image/png'},
            {'src': 'https://via.placeholder.com/512', 'sizes': '512x512', 'type': 'image/png'}]
}">
""", unsafe_allow_html=True)

st.caption("💡 手機使用提示：部署後，從 iOS Safari 點「分享 → 加到主畫面」即可像 App 一樣下載使用！")

st.title("🏢 公司新人 Onboarding 工具")
st.markdown("歡迎新同事！這裡提供公司政策資訊、PDF 原文與即時 Q&A。")

pdf_path = os.path.join(os.path.dirname(__file__), "policy.pdf")

if not os.path.exists(pdf_path):
    st.error("❌ 請確保 policy.pdf 存在於應用程式同一資料夾")
    st.stop()

st.header("📊 公司政策資訊（表格提取）")
try:
    with pdfplumber.open(pdf_path) as pdf:
        tables = []
        for i, page in enumerate(pdf.pages):
            table = page.extract_table()
            if table:
                df = pd.DataFrame(table[1:], columns=table[0])
                tables.append((i + 1, df))

    if tables:
        for page_num, df in tables:
            st.subheader(f"第 {page_num} 頁 表格")
            st.dataframe(df, use_container_width=True)
    else:
        st.info("PDF 中未偵測到表格，可直接閱讀原文或提問。")
except Exception as e:
    st.warning(f"解析 PDF 表格時出現問題：{e}")

st.header("📄 PDF 原文")
with open(pdf_path, "rb") as f:
    st.download_button(
        label="下載公司政策 PDF",
        data=f,
        file_name="公司政策手冊.pdf",
        mime="application/pdf",
    )

# Extract full text for Q&A context
pdf_text = ""
try:
    reader = PyPDF2.PdfReader(pdf_path)
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pdf_text += text + "\n"
    st.caption(f"PDF 共 {len(reader.pages)} 頁，已提取文字用於 Q&A。")
except Exception as e:
    st.warning(f"提取 PDF 文本時出現問題：{e}")

st.header("❓ 簡單 Q&A（問公司政策問題）")
question = st.text_input("例如：公司請假政策是什麼？年度健檢有幾天？")

if question:
    if not GEMINI_API_KEY or not _HAS_GENAI:
        st.error("無法使用 Q&A：請安裝 `google-genai` 並設定 `GEMINI_API_KEY` 環境變數。")
    else:
        with st.spinner("Gemini 正在思考..."):
            try:
                prompt = f"""
你是專業的 HR 助手，請用繁體中文、親切簡潔的語氣回答。
僅根據以下公司政策內容回答，不要添加外部知識。
如果問題不在內容中，請說「抱歉，這部分政策未涵蓋，請直接聯絡 HR。」

政策內容（截取前 8000 字，避免 token 超限）：
{pdf_text[:8000]}

新人問題：{question}
"""
                # Prefer an existing configured client; otherwise create one with the API key
                client = getattr(genai, 'client', None) or genai.Client(api_key=GEMINI_API_KEY)

                # Try a few model candidates to avoid hard-failing when a model name isn't available
                # Prefer newer Gemini 2.x IDs observed in the environment
                model_candidates = [
                    'models/gemini-2.5-flash',
                    'models/gemini-2.5-pro',
                    'models/gemini-flash-latest',
                    'models/gemini-pro-latest',
                    'models/gemini-2.0-flash',
                    'gemini-1.5-flash',
                ]
                response = None
                last_exc = None
                for m in model_candidates:
                    try:
                        response = client.models.generate_content(model=m, contents=prompt)
                        break
                    except Exception as e:
                        last_exc = e
                        # try next candidate
                        continue

                if response is None:
                    # If all candidates failed, try to list available models to give actionable feedback
                    model_list_info = None
                    try:
                        if hasattr(client, 'models') and hasattr(client.models, 'list'):
                            models_res = client.models.list()
                            # Try to extract model identifiers in a few possible shapes
                            try:
                                model_items = getattr(models_res, 'models', models_res)
                                model_ids = [getattr(mi, 'name', str(mi)) for mi in model_items]
                                model_list_info = ', '.join(model_ids)
                            except Exception:
                                model_list_info = str(models_res)
                    except Exception:
                        model_list_info = None

                    if model_list_info:
                        st.error(f"呼叫 Gemini 時發生錯誤：{last_exc}。可用模型包括：{model_list_info}")
                    else:
                        st.error(f"呼叫 Gemini 時發生錯誤：{last_exc}")
                else:
                    # response exposes a `text` property on this SDK
                    answer_text = getattr(response, 'text', None) or str(response)
                    st.markdown("**🤖 Gemini 回答：**")
                    st.write(answer_text)
            except Exception as e:
                st.error(f"呼叫 Gemini 時發生錯誤：{e}")

st.markdown("---")
st.markdown("### 使用說明")
st.write("- 本工具手機平板皆可順暢使用")
st.write("- iOS 用戶：部署後從 Safari 加到主畫面，即可離線瀏覽（基本快取）")
st.write("- 如需更新 PDF，請將新的 `policy.pdf` 放在應用程式資料夾中並重新部署")
st.write("Made with ❤️ by Python + Streamlit + Google Gemini")
