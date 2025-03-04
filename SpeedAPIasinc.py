import requests
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import io
import asyncio
import aiohttp


# Функция для получения данных из PageSpeed Insights API
async def fetch_pagespeed_data(api_key, url, strategy, session, semaphore):
    async with semaphore:
        base_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        params = {"url": url, "key": api_key, "strategy": strategy}
        async with session.get(base_url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                audits = data.get("lighthouseResult", {}).get("audits", {})
                metrics = data.get("loadingExperience", {}).get("metrics", {})

                # Функция для получения значений метрик без единиц измерения
                def get_numeric_value(metric_name):
                    value = audits.get(metric_name, {}).get("numericValue", "N/A")
                    if isinstance(value, (int, float)):
                        return round(value, 1)  # Округляем до одного знака после запятой для FCP, LCP и Speed Index
                    return "N/A"

                def get_p75_metric(metric_name):
                    return metrics.get(metric_name, {}).get("percentiles", {}).get("p75", "N/A")

                # Получаем метрики без единиц измерения
                # Получаем метрики с округлением до десятых секунд
                fcp = round(get_numeric_value("first-contentful-paint") / 1000, 1) if isinstance(
                    get_numeric_value("first-contentful-paint"), (int, float)) else "N/A"  # First Contentful Paint
                lcp = round(get_numeric_value("largest-contentful-paint") / 1000, 1) if isinstance(
                    get_numeric_value("largest-contentful-paint"), (int, float)) else "N/A"  # Largest Contentful Paint

                tbt = audits.get("total-blocking-time", {}).get("numericValue", "N/A")  # Total Blocking Time
                cls = get_numeric_value("cumulative-layout-shift")  # Cumulative Layout Shift
                speed_index = get_numeric_value("speed-index")  # Speed Index
                ttfb = audits.get("server-response-time", {}).get("numericValue", "N/A")  # Time to First Byte

                # Преобразуем TBT и TTFB в секунды
                if isinstance(tbt, (int, float)):
                    tbt = round(tbt / 1000, 2)  # TBT в секунды
                if isinstance(ttfb, (int, float)):
                    ttfb = round(ttfb / 1000, 2)  # TTFB в секунды

                # Получаем общий score
                score = data.get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score", 0) * 100

                # Возвращаем данные без единиц измерения
                header_data = {
                    "URL": url,
                    "First Contentful Paint": fcp,
                    "Largest Contentful Paint": lcp,
                    "Total Blocking Time": tbt,
                    "Cumulative Layout Shift": cls,
                    "Speed Index": speed_index,
                    "TTFB": ttfb,
                    "Score": int(score)
                }

                return header_data
            else:
                return {"URL": url, "Score": "N/A"}


# Асинхронное получение данных по списку URL
async def fetch_multiple_pagespeed_scores(api_key, urls, strategy, progress_bar, status_text):
    semaphore = asyncio.Semaphore(3)  # Ограничение на количество одновременных запросов
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_pagespeed_data(api_key, url, strategy, session, semaphore) for url in urls]
        results = []
        for i, result in enumerate(asyncio.as_completed(tasks)):
            results.append(await result)
            progress_bar.progress((i + 1) / len(urls))
            status_text.text(f"Обработано: {i + 1}/{len(urls)}")
        return results


# Интерфейс Streamlit
st.title("PageSpeed Insights Checker")
api_key = st.text_input("Введите API ключ Google PageSpeed:", "")

strategy = st.radio("Выберите стратегию проверки:", ["mobile", "desktop"], index=0)

option = st.radio("Выберите источник URL:", ["Ввести вручную", "Загрузить XML карту"])
urls = []

if option == "Ввести вручную":
    url_input = st.text_area("Введите список URL (по одному в строке):")
    if url_input:
        urls = [url.strip() for url in url_input.split("\n") if url.strip()]
else:
    sitemap_url = st.text_input("Введите URL карты XML сайта:")
    if sitemap_url:
        try:
            response = requests.get(sitemap_url)
            if response.status_code == 200:
                tree = ET.ElementTree(ET.fromstring(response.text))
                root = tree.getroot()
                urls = [elem.text for elem in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
            else:
                st.warning(f"Не удалось загрузить карту сайта. Статус: {response.status_code}")
        except Exception as e:
            st.error(f"Ошибка при загрузке карты сайта: {str(e)}")

if st.button("Проверить", disabled=False):
    if not api_key:
        st.warning("Введите API ключ")
    elif not urls:
        st.warning("Введите хотя бы один URL или загрузите XML-карту")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()

        results = asyncio.run(fetch_multiple_pagespeed_scores(api_key, urls, strategy, progress_bar, status_text))
        df = pd.DataFrame(results)

        # Выводим таблицу с метками, но без единиц измерения
        st.subheader("Метрики по URL")
        st.dataframe(df[["URL", "First Contentful Paint", "Largest Contentful Paint", "Total Blocking Time",
                         "Cumulative Layout Shift", "Speed Index", "TTFB", "Score"]], use_container_width=True)

        # Скачивание CSV и Excel без скрытия таблицы
        csv = df.to_csv(index=False).encode("utf-8")
        excel_buffer = io.BytesIO()
        df.to_excel(excel_buffer, index=False, engine="openpyxl")
        excel_buffer.seek(0)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button("Скачать CSV", data=csv, file_name="pagespeed_results.csv", mime="text/csv")
        with col2:
            st.download_button("Скачать Excel", data=excel_buffer, file_name="pagespeed_results.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
