import streamlit as st
import datetime as dt
import time
import urllib.request
import json
import pyotp
from SmartApi import SmartConnect

# Angel One API credentials
api_key = 'Vk5ILvIy'
clientId = 'S61437367'
pwd = '2626'
token = "PCBMOECEEGO5O4XTZ3WTTGTICU"
totp = pyotp.TOTP(token).now()

# Initialize SmartConnect
obj = SmartConnect(api_key)
data = obj.generateSession(clientId, pwd, totp)
authToken = data['data']['jwtToken']
refreshToken = data['data']['refreshToken']
feed_token = obj.getfeedToken()
res = obj.getProfile(refreshToken)
obj.generateToken(refreshToken)
res = res['data']['exchanges']

# Instrument list from Angel One
instrument_url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
response = urllib.request.urlopen(instrument_url)
instrument_list = json.loads(response.read())

# Function to get nearest strike price
def get_nearest_strike_price(entry_price):
    return round(entry_price / 100) * 100

# Function to fetch historical data
def fetch_historical_data(exchange, symbol, token, start_datetime, end_datetime):
    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": "ONE_MINUTE",
        "fromdate": start_datetime.strftime('%Y-%m-%d %H:%M'),
        "todate": end_datetime.strftime('%Y-%m-%d %H:%M')
    }
    
    try:
        hist_data = obj.getCandleData(params)
        if hist_data and "data" in hist_data:
            return hist_data["data"]
    except Exception as e:
        st.error(f"Error fetching historical data: {e}")
    return []

# Function to get the highest option price from 9:15 to 9:19
def get_high_of_option(symbol_token, start_time, end_time):
    expiry_date="11SEP24"
    option_symbol = f'BANKNIFTY{expiry_date}{symbol_token}'
    symbol_token = next((item['token'] for item in instrument_list if item['symbol'] == option_symbol), None)
    historical_data = fetch_historical_data("NFO", f"BANKNIFTY{expiry_date}{symbol_token}", symbol_token, start_time, end_time)
    if historical_data:
        high_prices = [candle[2] for candle in historical_data]  # Extracting the high price
        return max(high_prices) if high_prices else None
    return None

# Function to fetch live price
def get_live_price(exchange, tradingsymbol, symboltoken):
    expiry_date="11SEP24"
    option_symbol = f'BANKNIFTY{expiry_date}{symboltoken}'
    symbol_token = next((item['token'] for item in instrument_list if item['symbol'] == option_symbol), None)
    try:
        live_data = obj.ltpData(exchange, tradingsymbol, symbol_token)
        if live_data and 'data' in live_data and live_data['data']:
            return live_data['data']['ltp']
    except Exception as e:
        st.error(f"Error fetching live price: {e}")
    return None

# Function to monitor and exit trade
def monitor_and_exit(symbol_token, entry_price, exit_price, stop_loss, exit_details, tradingsymbol):
    while True:
        time.sleep(1)  # Delay to avoid rate limits
        live_price = get_live_price("NFO", tradingsymbol, symbol_token)
        if live_price is None:
            continue
                    
        if live_price >= exit_price or live_price <= stop_loss:
            st.write(f"Exited at {live_price}")
            break

# Function to place an order
def place_order(tradingsymbol, symbol_token, transaction_type, order_type="MARKET", price=None):
    lot_size = 15  # Bank Nifty lot size
    order_params = {
        "variety": "NORMAL",
        "tradingsymbol": tradingsymbol,
        "symboltoken": symbol_token,
        "transactiontype": transaction_type,
        "exchange": "NFO",
        "ordertype": order_type,
        "producttype": "INTRADAY",
        "duration": "DAY",
        "quantity": lot_size  # Set to the lot size
    }
    if order_type == "LIMIT" and price is not None:
        order_params["price"] = price

    order_id = obj.placeOrder(order_params)
    st.write("Order placed")
    return order_id

# Live strategy function
def live_strategy():
    entry_details = []
    high = 0
    low = float('inf')
    prices = []

    start_time = dt.datetime.combine(dt.datetime.now().date(), dt.time(9, 16))
    end_time = dt.datetime.combine(dt.datetime.now().date(), dt.time(9, 20))
    
    banknifty_price = fetch_historical_data("NSE", "BANKNIFTY", "99926009", start_time, end_time)
    if banknifty_price:
        for candle in banknifty_price:
            candle_time, open_price, high_price, low_price, close_price, volume = candle
            prices.append((high_price, low_price))

    if prices:
        high = max(price[0] for price in prices)
        low = min(price[1] for price in prices)
        st.write(f"Final High: {high}")
        st.write(f"Final Low: {low}")
        
    ce_strike_price = get_nearest_strike_price(high)
    pe_strike_price = get_nearest_strike_price(low)
    st.write(f"CE Strike Price: {ce_strike_price}, PE Strike Price: {pe_strike_price}")

    ce_high = get_high_of_option(f"{ce_strike_price}CE", start_time, end_time)
    pe_high = get_high_of_option(f"{pe_strike_price}PE", start_time, end_time)

    if ce_high is None or pe_high is None:
        st.error("Failed to fetch option high prices.")
        return

    st.write(f"CE High from 9:16 to 9:20: {ce_high}")
    st.write(f"PE High from 9:16 to 9:20: {pe_high}")

    trade_executed = False
    while not trade_executed and dt.datetime.now().time() > dt.time(9, 20):
        
        ce_live_price = get_live_price("NFO", f"BANKNIFTY{ce_strike_price}CE", f"{ce_strike_price}CE")
        pe_live_price = get_live_price("NFO", f"BANKNIFTY{pe_strike_price}PE", f"{pe_strike_price}PE")

        if ce_live_price and ce_live_price >= ce_high + 5:
            st.write(f"CE Option triggered at {ce_live_price} (CE High + 5: {ce_high + 5})")
            expiry_date="11SEP24"
            option_symbol = f'BANKNIFTY{expiry_date}{f"{ce_strike_price}CE"}'
            symbol_token = next((item['token'] for item in instrument_list if item['symbol'] == option_symbol), None)
            place_order(f"BANKNIFTY{expiry_date}{ce_strike_price}CE", symbol_token, "BUY")
            trade_executed = True
            break

        if pe_live_price and pe_live_price >= pe_high + 5:
            st.write(f"PE Option triggered at {pe_live_price} (PE High + 5: {pe_high + 5})")
            expiry_date="11SEP24"
            option_symbol = f'BANKNIFTY{expiry_date}{f"{pe_strike_price}PE"}'
            symbol_token = next((item['token'] for item in instrument_list if item['symbol'] == option_symbol), None)
            place_order(f"BANKNIFTY{expiry_date}{pe_strike_price}PE", symbol_token, "BUY")
            trade_executed = True
            break

        time.sleep(2)

    st.write("Trade executed. Monitoring exit conditions...")


st.title("BankNifty Trading Strategy")
if st.button('Execute Strategy'):
    live_strategy()
    st.write("Strategy run successfully.")