import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth

AFFILIATE_TAG = "petpromos0f-20"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}
REQUEST_TIMEOUT = 10

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

# ---------------- Amazon Scraper ----------------
def pesquisar_amazon_br(query):
    termo = query.strip().replace(" ", "+")
    url = f"https://www.amazon.com.br/s?k={termo}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
    except:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    resultado = soup.select_one("div.s-main-slot div[data-component-type='s-search-result']")
    if not resultado:
        return None

    asin = resultado.get("data-asin", "").strip()
    titulo_tag = resultado.select_one("h2 a span")
    titulo = titulo_tag.get_text().strip() if titulo_tag else None

    pre_whole = resultado.select_one("span.a-price-whole")
    pre_frac = resultado.select_one("span.a-price-fraction")
    if pre_whole:
        preco = pre_whole.get_text().strip()
        if pre_frac:
            preco += "," + pre_frac.get_text().strip()
        preco = re.sub(r"[^\d,]", "", preco)
        preco = "R$ " + preco
    else:
        preco = None

    img_tag = resultado.select_one("img.s-image")
    img_url = img_tag.get("src") or img_tag.get("data-src") if img_tag else None
    if img_url and img_url.startswith("//"):
        img_url = "https:" + img_url

    return {"title": titulo, "price": preco, "img_url": img_url, "asin": asin}

def gerar_link_afiliado(asin):
    if not asin:
        return None
    return f"https://www.amazon.com.br/dp/{asin}/?tag={AFFILIATE_TAG}"

# ---------------- Mercado Livre + Playwright ----------------
PROXY_SOURCE = "https://www.proxy-list.download/api/v1/get?type=http"

def pegar_proxies():
    try:
        r = requests.get(PROXY_SOURCE, timeout=10)
        return [p.strip() for p in r.text.strip().split("\n") if p.strip()]
    except:
        return []

def delay_humano(min_ms=500, max_ms=1500):
    time.sleep(random.uniform(min_ms/1000, max_ms/1000))

def scroll_humano(page):
    for _ in range(random.randint(3,6)):
        page.mouse.wheel(0, random.randint(300,900))
        delay_humano(500,1200)

def buscar_mercadolivre_playwright(query, proxies):
    proxy = random.choice(proxies) if proxies else None
    with sync_playwright() as p:
        args = {"headless": True}
        if proxy:
            args["proxy"] = {"server": f"http://{proxy}"}

        browser = p.chromium.launch(**args)
        context = browser.new_context()
        page = context.new_page()
        stealth(page)

        url = f"https://lista.mercadolivre.com.br/{query.replace(' ','-')}"
        try:
            page.goto(url, timeout=60000)
        except:
            browser.close()
            return None

        delay_humano(1500,2500)
        scroll_humano(page)

        items = page.query_selector_all("li.ui-search-layout__item")
        if not items:
            browser.close()
            return None

        primeiro = items[0]
        title_el = primeiro.query_selector("h2.ui-search-item__title")
        price_el = primeiro.query_selector("span.price-tag-fraction")
        link_el = primeiro.query_selector("a.ui-search-item__group__element")
        thumb_el = primeiro.query_selector("img.ui-search-result-image__element")

        resultado = {}
        if title_el: resultado['title'] = title_el.inner_text()
        if price_el: resultado['price'] = price_el.inner_text()
        if link_el: resultado['link'] = link_el.get_attribute("href")
        if thumb_el: resultado['thumbnail'] = thumb_el.get_attribute("src")

        browser.close()
        return resultado

# ---------------- Telegram Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Olá! Me envie o nome da ração e eu busco na Amazon + Mercado Livre (Playwright + stealth)."
    )

async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /buscar <nome do produto>")
    termo = " ".join(context.args)
    await update.message.reply_text(f"🔎 Buscando: {termo} …")

    amazon = pesquisar_amazon_br(termo)
    proxies = pegar_proxies()
    ml = buscar_mercadolivre_playwright(termo, proxies)

    if amazon:
        link_amz = gerar_link_afiliado(amazon["asin"])
        texto_amz = (
            "🟦 *Amazon Brasil*\n"
            f"📦 *{amazon['title']}*\n"
            f"💰 {amazon['price']}\n"
            f"[🛒 Comprar]({link_amz})\n\n"
        )
        if amazon["img_url"]:
            await context.bot.send_photo(update.effective_chat.id, amazon["img_url"], caption=texto_amz, parse_mode="Markdown")
        else:
            await update.message.reply_text(texto_amz, parse_mode="Markdown")
    else:
        await update.message.reply_text("Amazon: nenhum resultado.", parse_mode="Markdown")

    if ml:
        texto_ml = (
            "🟨 *Mercado Livre*\n"
            f"📦 *{ml.get('title','N/A')}*\n"
            f"💰 R$ {ml.get('price','N/A')}\\n"
            f"[🛒 Ver no Mercado Livre]({ml.get('link','')})\n"
        )
        if ml.get("thumbnail"):
            await context.bot.send_photo(update.effective_chat.id, ml["thumbnail"], caption=texto_ml, parse_mode="Markdown")
        else:
            await update.message.reply_text(texto_ml, parse_mode="Markdown")
    else:
        await update.message.reply_text("Mercado Livre: nenhum resultado.", parse_mode="Markdown")

# ---------------- Inicialização ----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))
    print("Bot rodando…")
    app.run_polling()

if __name__ == "__main__":
    main()
