"""
Trading Strategy Return Analysis Tool

Usage:
1. Run directly: python get_return.py
2. Optionally filter with arguments such as:
   python get_return.py --agent base_agent
   python get_return.py --asset AAPL
   python get_return.py --agent react_agent --asset AAPL --model llama-3.3-70b

The script automatically scans trading result files under results/.
Report files are excluded.

File naming format: results/{agent}_{task}_{asset}_{model}.json
Example: results/base_agent_trading_AAPL_llama-3.3-70b.json
"""

import argparse
import json
import os
import pickle
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import ttest_rel
from datetime import datetime, timedelta

# Global price cache to avoid repeated API calls
_price_cache = {}
CACHE_FILE = "cache/price_cache.pkl"
CRYPTO_SYMBOLS = {
    'BTC', 'ETH', 'ADA', 'SOL', 'DOT', 'LINK', 'UNI', 'MATIC', 'AVAX', 'ATOM'
}

def _to_yfinance_symbol(symbol):
    """Convert internal asset symbol to a yfinance ticker."""
    if symbol in CRYPTO_SYMBOLS:
        return f"{symbol}-USD"
    return symbol

def get_asset_price(symbol, date_str):
    """Fetch the asset close price for a specific date.

    Returns None when no market data exists for that day.
    """
    ticker = _to_yfinance_symbol(symbol)
    start_date = datetime.fromisoformat(date_str)
    end_date = start_date + timedelta(days=1)

    try:
        hist = yf.Ticker(ticker).history(
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            auto_adjust=True,
        )
    except Exception as e:
        print(f"Warning: failed to fetch price for {symbol} on {date_str}: {e}")
        return None

    if hist.empty or 'Close' not in hist:
        return None

    close_price = hist['Close'].dropna()
    if close_price.empty:
        return None

    return float(close_price.iloc[-1])

def load_price_cache():
    """Load price cache from local pkl file"""
    global _price_cache
    
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                _price_cache = pickle.load(f)
            
            # Count loaded cache information
            total_entries = sum(len(dates) for dates in _price_cache.values())
            symbols = list(_price_cache.keys())
            if total_entries > 0:
                print(f"📦 已加载价格缓存: {len(symbols)} 个资产，共 {total_entries} 个价格数据点")
        else:
            _price_cache = {}
            print(f"ℹ️  价格缓存文件不存在，将创建新缓存: {CACHE_FILE}")
    except Exception as e:
        _price_cache = {}
        print(f"⚠️  加载价格缓存失败: {e}")

def save_price_cache():
    """Save price cache to local pkl file"""
    global _price_cache
    
    try:
        # Ensure cache directory exists
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(_price_cache, f)
        
        # Count saved cache information
        total_entries = sum(len(dates) for dates in _price_cache.values())
        symbols = list(_price_cache.keys())
        
    except Exception as e:
        pass

def preload_prices(symbol, start_date, end_date):
    """Preload all price data within specified time range to cache"""
    global _price_cache
    
    # On first call, load cache from local file
    if not _price_cache:
        load_price_cache()
    
    # Generate date range
    dates = pd.date_range(start=start_date, end=end_date, freq='D')
    cache_key = symbol
    
    if cache_key not in _price_cache:
        _price_cache[cache_key] = {}
    
    # Count API calls and cache hits
    api_calls = 0
    cached_hits = 0
    
    # Batch fetch price data - only call API for dates not in cache
    for current_date in dates:
        date_str = current_date.strftime('%Y-%m-%d')
        if date_str not in _price_cache[cache_key]:
            # Only call API if not in cache
            price = get_asset_price(symbol, date_str)
            _price_cache[cache_key][date_str] = price
            api_calls += 1
        else:
            # Price already in cache, skip API call
            cached_hits += 1
    
    # Save cache if there were new API calls
    if api_calls > 0:
        save_price_cache()
        print(f"📊 {symbol}: 从缓存加载 {cached_hits} 个价格，新增获取 {api_calls} 个价格")
    elif cached_hits > 0:
        print(f"✅ {symbol}: 所有 {cached_hits} 个价格均从缓存加载，无需API调用")

def get_cached_price(symbol, date_str):
    """Get price from cache, call API directly if not in cache"""
    global _price_cache
    
    # On first call, load cache from local file
    if not _price_cache:
        load_price_cache()
    
    cache_key = symbol
    if cache_key in _price_cache and date_str in _price_cache[cache_key]:
        # Get from cache
        return _price_cache[cache_key][date_str]
    else:
        # If not in cache, call API directly (fallback solution)
        price = get_asset_price(symbol, date_str)
        # Cache the API result as well
        if cache_key not in _price_cache:
            _price_cache[cache_key] = {}
        _price_cache[cache_key][date_str] = price
        # Immediately save newly fetched price
        save_price_cache()
        return price

def get_recommendation_price(rec_map, date_str, symbol=None):
    """Get price from result-file recommendations first, then fall back if needed."""
    rec = rec_map.get(date_str)
    if rec is not None:
        price = rec.get('price')
        if price is not None:
            try:
                return float(price)
            except (TypeError, ValueError):
                pass

    if symbol is None:
        return None
    return get_cached_price(symbol, date_str)

def clear_price_cache():
    """Save price cache but don't clear memory (for compatibility with existing code)"""
    global _price_cache
    
    # Count cache information
    total_entries = sum(len(dates) for dates in _price_cache.values())
    symbols = list(_price_cache.keys())
    
    # Save to file instead of clearing
    save_price_cache()

def force_clear_cache():
    """Force clear memory cache (actual clearing function)"""
    global _price_cache
    
    # Count cache information
    total_entries = sum(len(dates) for dates in _price_cache.values())
    symbols = list(_price_cache.keys())
    
    # Save first then clear
    save_price_cache()
    _price_cache.clear()

def run_compounding_simulation(recommendations, initial_capital=100000, trade_fee=0.0005, strategy='long_short', trading_mode='normal', asset_type='stock', symbol=None):
    """
    Runs a realistic trading simulation with compounding capital and returns a daily capital series.
    
    trading_mode:
    - 'normal': Original strategy
        - HOLD: keep current position
        - BUY: open long if flat, ignore if in position
        - SELL: open short if flat, close if long
    
    - 'aggressive': New strategy
        - HOLD: force close to flat
        - BUY: close short (if short) then open long
        - SELL: close long (if long) then open short
    """
    capital = float(initial_capital)
    position = 'FLAT'
    entry_price = 0
    capital_series = []

    rec_map = {rec['date']: rec for rec in recommendations}
    start_date = datetime.fromisoformat(recommendations[0]['date'])
    end_date = datetime.fromisoformat(recommendations[-1]['date'])
    
    # symbol must be provided, no default values
    if symbol is None:
        raise ValueError("Symbol must be provided for run_compounding_simulation, cannot use default values")
    
    # Use all calendar days (let price fetching function decide if valid)
    dates = pd.date_range(start=start_date, end=end_date, freq='D')
    
    # Record previous trading day's capital for filling non-trading days
    last_capital = capital
    
    for current_date in dates:
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Actually get current day's price (based on asset type)
        current_price = get_recommendation_price(rec_map, date_str, symbol)
        if current_price is None:  # If price is null (market closed), skip this day
            capital_series.append(last_capital)
            continue

        daily_capital = capital
        if position == 'LONG':
            daily_capital = capital * (current_price / entry_price) if entry_price != 0 else capital
        elif position == 'SHORT':
            daily_capital = capital * (1 + (entry_price - current_price) / entry_price) if entry_price != 0 else capital

        # Execute trades for the current day BEFORE recording capital
        # Check if the date exists in recommendations, default to HOLD if not
        if date_str in rec_map:
            action = rec_map[date_str].get('recommended_action', 'HOLD')
        else:
            action = 'HOLD'  # Default action for missing dates
        
        if trading_mode == 'normal':  # Original strategy: HOLD keeps position
            if action == 'HOLD':
                # Keep current position, do nothing
                pass
            elif action == 'BUY':
                if position == 'FLAT':
                    position, entry_price = 'LONG', current_price
                    capital *= (1 - trade_fee)
                    daily_capital = capital  # Update daily capital after trade
                elif position == 'SHORT':
                    # Close short position first
                    return_pct = (entry_price - current_price) / entry_price if entry_price != 0 else 0
                    capital *= (1 + return_pct) * (1 - trade_fee)
                    # Then open long position
                    position, entry_price = 'LONG', current_price
                    capital *= (1 - trade_fee)
                    daily_capital = capital
            elif action == 'SELL':
                if position == 'LONG':
                    return_pct = (current_price - entry_price) / entry_price if entry_price != 0 else 0
                    capital *= (1 + return_pct) * (1 - trade_fee)
                    position, entry_price = 'FLAT', 0
                    daily_capital = capital  # Update daily capital after trade
                elif position == 'FLAT' and strategy == 'long_short':
                    position, entry_price = 'SHORT', current_price
                    capital *= (1 - trade_fee)
                    daily_capital = capital  # Update daily capital after trade
                    
        else:  # New strategy: HOLD closes position, BUY/SELL switches position directly
            if action == 'HOLD':  # Force close position
                if position == 'LONG':
                    return_pct = (current_price - entry_price) / entry_price if entry_price != 0 else 0
                    capital *= (1 + return_pct) * (1 - trade_fee)
                    position, entry_price = 'FLAT', 0
                    daily_capital = capital
                elif position == 'SHORT':
                    return_pct = (entry_price - current_price) / entry_price if entry_price != 0 else 0
                    capital *= (1 + return_pct) * (1 - trade_fee)
                    position, entry_price = 'FLAT', 0
                    daily_capital = capital
            elif action == 'BUY':
                if position == 'SHORT':  # First close short position
                    return_pct = (entry_price - current_price) / entry_price if entry_price != 0 else 0
                    capital *= (1 + return_pct) * (1 - trade_fee)
                    position, entry_price = 'FLAT', 0
                    daily_capital = capital  # Update daily_capital
                if position == 'FLAT':  # Then open long position
                    position, entry_price = 'LONG', current_price
                    capital *= (1 - trade_fee)
                    daily_capital = capital
            elif action == 'SELL':
                if position == 'LONG':  # First close long position
                    return_pct = (current_price - entry_price) / entry_price if entry_price != 0 else 0
                    capital *= (1 + return_pct) * (1 - trade_fee)
                    position, entry_price = 'FLAT', 0
                    daily_capital = capital  # Update daily_capital
                if position == 'FLAT' and strategy == 'long_short':  # Then open short position
                    position, entry_price = 'SHORT', current_price
                    capital *= (1 - trade_fee)
                    daily_capital = capital
        
        # Record capital after all trades are executed
        capital_series.append(daily_capital)
        last_capital = daily_capital
        
        # Force close position on the last day
        if current_date == dates[-1] and position != 'FLAT':
            if position == 'LONG':
                return_pct = (current_price - entry_price) / entry_price if entry_price != 0 else 0
                capital *= (1 + return_pct) * (1 - trade_fee)
            elif position == 'SHORT':
                return_pct = (entry_price - current_price) / entry_price if entry_price != 0 else 0
                capital *= (1 + return_pct) * (1 - trade_fee)
            position, entry_price = 'FLAT', 0
            capital_series[-1] = capital  # Update the last capital value
    
    return capital_series

def calculate_buy_and_hold_series(recommendations, initial_capital=100000, trade_fee=0.0005, asset_type='stock', symbol=None):
    """Calculate buy and hold strategy performance"""
    capital_series = []
    rec_map = {rec['date']: rec for rec in recommendations}
    start_date = datetime.fromisoformat(recommendations[0]['date'])
    end_date = datetime.fromisoformat(recommendations[-1]['date'])
    
    # symbol must be provided, no default values
    if symbol is None:
        raise ValueError("Symbol must be provided for calculate_buy_and_hold_series, cannot use default values")
    
    # Get first valid price as buy price
    buy_price = None
    first_date_str = start_date.strftime('%Y-%m-%d')
    buy_price = get_recommendation_price(rec_map, first_date_str, symbol)
    
    if buy_price is None:
        # If no price on first day, find first valid price
        current_date = start_date
        while current_date <= end_date and buy_price is None:
            date_str = current_date.strftime('%Y-%m-%d')
            buy_price = get_recommendation_price(rec_map, date_str, symbol)
            current_date += timedelta(days=1)
    
    if buy_price is None or buy_price <= 0:
        # If no valid price throughout the period, return empty sequence
        print(f"Warning: No valid buy price found for {symbol} in period {start_date} to {end_date}")
        return []
    
    # Buy on first day, charge opening fee
    capital = initial_capital * (1 - trade_fee)
    
    # Use all calendar days (let price fetching function decide if valid)
    dates = pd.date_range(start=start_date, end=end_date, freq='D')
    
    last_price = buy_price
    for i, current_date in enumerate(dates):
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Actually get current day's price (based on asset type)
        current_price = get_recommendation_price(rec_map, date_str, symbol)
        
        # If price is null, skip this day and use last valid price
        if current_price is None:
            daily_capital = capital * (last_price / buy_price) if buy_price != 0 else capital
            capital_series.append(daily_capital)
            continue
        
        # Calculate current market value
        daily_capital = capital * (current_price / buy_price) if buy_price != 0 else capital
        
        # Sell on last day, charge closing fee
        if i == len(dates) - 1:  # Use index to determine last day
            daily_capital *= (1 - trade_fee)
            
        capital_series.append(daily_capital)
        last_price = current_price
        
    return capital_series

def get_daily_returns(capital_series):
    """Calculate daily returns from capital series"""
    series = pd.Series(capital_series)
    return series.pct_change().fillna(0)

def calculate_metrics(capital_series, recommendations, asset_type='stock', bh_series=None):
    """
    Calculate performance metrics for different asset types
    
    Parameters:
    - capital_series: list of daily capital values
    - recommendations: list of trading recommendations
    - asset_type: 'stock' or 'crypto'
    - bh_series: buy and hold capital series for comparison (optional)
    """
    if len(capital_series) == 0:
        result = {
            'total_return': 0,
            'ann_return': 0,
            'ann_vol': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'days_outperforming_bh': 0,
            'avg_daily_excess_return': 0
        }
        if bh_series is not None:
            return result
        else:
            return {k: v for k, v in result.items() if k not in ['days_outperforming_bh', 'avg_daily_excess_return']}
    
    daily_returns = get_daily_returns(capital_series)

    # Total Return
    total_return = (capital_series[-1] - capital_series[0]) / capital_series[0] * 100

    # Choose annualization parameters based on asset type
    if asset_type == 'stock':
        annual_days = 252  # Stock trading days per year
        # For stocks, the capital series includes calendar days; weekends/holidays
        # create zero returns that artificially depress volatility.
        # Filter out zero-return days to approximate trading days only.
        trading_returns = daily_returns[daily_returns != 0]
        effective_returns = trading_returns if len(trading_returns) > 0 else daily_returns
        n_days_effective = len(effective_returns) if len(effective_returns) > 0 else len(daily_returns)
        ann_vol = (effective_returns.std() * np.sqrt(annual_days) * 100) if len(effective_returns) > 1 else 0
        # Annualized return uses effective trading day count
        if n_days_effective > 1:
            ann_return = (((capital_series[-1] / capital_series[0]) ** (annual_days / n_days_effective)) - 1) * 100
        else:
            ann_return = total_return
    else:  # crypto
        annual_days = 365  # Cryptocurrency trades year-round
        n_days_effective = len(daily_returns)
        ann_vol = daily_returns.std() * np.sqrt(annual_days) * 100 if len(daily_returns) > 1 else 0
        if n_days_effective > 1:
            ann_return = (((capital_series[-1] / capital_series[0]) ** (annual_days / n_days_effective)) - 1) * 100
        else:
            ann_return = total_return

    # Sharpe Ratio (assuming risk-free rate = 0)
    # Use standard daily mean/std approach with consistent day count per asset type
    if asset_type == 'stock':
        sharpe_base_returns = effective_returns
    else:
        sharpe_base_returns = daily_returns

    mean_daily = sharpe_base_returns.mean() if len(sharpe_base_returns) > 0 else 0
    std_daily = sharpe_base_returns.std() if len(sharpe_base_returns) > 1 else 0

    if std_daily and std_daily > 0:
        sharpe_ratio = (mean_daily / std_daily) * np.sqrt(annual_days)
    else:
        sharpe_ratio = 0
    
    # Maximum Drawdown
    capital_series_pd = pd.Series(capital_series)
    rolling_max = capital_series_pd.expanding().max()
    drawdowns = (capital_series_pd - rolling_max) / rolling_max
    max_drawdown = drawdowns.min() * 100 if len(drawdowns) > 0 else 0
    
    result = {
        'total_return': total_return,
        'ann_return': ann_return,
        'ann_vol': ann_vol,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown
    }
    
    # Calculate buy-and-hold comparison metrics if bh_series is provided
    if bh_series is not None and len(bh_series) > 0 and len(bh_series) == len(capital_series):
        # Calculate daily returns for both strategies (for Days > BH calculation)
        strategy_daily_returns = get_daily_returns(capital_series)
        bh_daily_returns = get_daily_returns(bh_series)
        
        # Filter for trading days (for Days > BH calculation)
        exclude_first_day = pd.Series([False] + [True] * (len(strategy_daily_returns) - 1), index=strategy_daily_returns.index)
        is_market_open = (strategy_daily_returns != 0) | (bh_daily_returns != 0)
        trading_days_mask = is_market_open & exclude_first_day
        
        total_trading_days = len(trading_days_mask[trading_days_mask])
        
        if total_trading_days > 0:
            # Calculate cumulative returns for all days (relative to day 0)
            initial_capital = capital_series[0] if len(capital_series) > 0 else 100000
            initial_bh_capital = bh_series[0] if len(bh_series) > 0 else 100000
            
            strategy_cumulative_returns = [(cap - initial_capital) / initial_capital for cap in capital_series]
            bh_cumulative_returns = [(cap - initial_bh_capital) / initial_bh_capital for cap in bh_series]
            
            # Filter to market-open days (exclude first day and non-trading days)
            trading_strategy_cumulative = pd.Series(strategy_cumulative_returns)[trading_days_mask]
            trading_bh_cumulative = pd.Series(bh_cumulative_returns)[trading_days_mask]
            
            # Count days where strategy cumulative return > buy-hold cumulative return
            outperforming_days = (trading_strategy_cumulative > trading_bh_cumulative).sum()
            days_outperforming_bh_pct = (outperforming_days / total_trading_days) * 100
            
            # Calculate daily excess cumulative return (strategy cumulative - buy hold cumulative)
            daily_excess_cumulative = [s - b for s, b in zip(strategy_cumulative_returns, bh_cumulative_returns)]
            
            # Filter to market-open days
            trading_excess_cumulative = pd.Series(daily_excess_cumulative)[trading_days_mask]
            
            # Calculate average daily excess cumulative return
            avg_daily_excess_return = trading_excess_cumulative.mean() * 100
        else:
            days_outperforming_bh_pct = 0
            avg_daily_excess_return = 0
        
        result['days_outperforming_bh'] = days_outperforming_bh_pct
        result['avg_daily_excess_return'] = avg_daily_excess_return
    elif bh_series is not None:
        # If bh_series provided but lengths don't match, set defaults
        result['days_outperforming_bh'] = 0
        result['avg_daily_excess_return'] = 0
    
    return result

def print_metrics_table(strategies_data, headers):
    """Print formatted metrics table"""
    # Check if any strategy has buy-and-hold comparison metrics
    has_bh_metrics = any('days_outperforming_bh' in data for _, data in strategies_data)
    
    metrics = ['total_return', 'ann_return', 'ann_vol', 'sharpe_ratio', 'max_drawdown']
    metric_headers = {
        'total_return': 'Total Return % (↑)',
        'ann_return': 'Ann. Return % (↑)',
        'ann_vol': 'Ann. Vol % (↓)',
        'sharpe_ratio': 'Sharpe Ratio (↑)',
        'max_drawdown': 'Max DD % (↓)'
    }
    
    # Add buy-and-hold comparison metrics if available
    if has_bh_metrics:
        metrics.extend(['days_outperforming_bh', 'avg_daily_excess_return'])
        metric_headers['days_outperforming_bh'] = 'Days > BH % (↑)'
        metric_headers['avg_daily_excess_return'] = 'Avg Daily Gap % (↑)'
    
    # Calculate column widths
    col_widths = {m: max(12, len(metric_headers[m]) + 1) for m in metrics}
    
    # Print header
    header_line = f"{'Strategy':<20} | " + " | ".join(f"{metric_headers[m]:>{col_widths[m]}}" for m in metrics)
    print(header_line)
    print("-" * len(header_line))
    
    # Print strategy data
    for name, data in strategies_data:
        line_parts = [f"{name:<20}"]
        for metric in metrics:
            if metric in data:
                if metric == 'days_outperforming_bh':
                    # Display as percentage with 2 decimal places
                    line_parts.append(f"{data[metric]:>{col_widths[metric]}.2f}")
                else:
                    line_parts.append(f"{data[metric]:>{col_widths[metric]}.2f}")
            else:
                # If metric not available, show dash
                line_parts.append(f"{'-':>{col_widths[metric]}}")
        line = " | ".join(line_parts)
        print(line)

def parse_result_filename(filename):
    """Parse a trading result filename into agent, asset, and model."""
    if not filename.endswith('.json'):
        return None

    base_name = filename[:-5]
    parts = base_name.split('_')
    if len(parts) < 4:
        return None

    task_idx = None
    for idx, part in enumerate(parts):
        if part in {'trading', 'report'}:
            task_idx = idx
            break

    if task_idx is None or task_idx == 0 or task_idx >= len(parts) - 2:
        return None

    task = parts[task_idx]
    if task != 'trading':
        return None

    agent = '_'.join(parts[:task_idx])
    asset = parts[task_idx + 1]
    model = '_'.join(parts[task_idx + 2 :])

    if not agent or not asset or not model:
        return None

    return agent, asset, model

def discover_available_files(results_dir='results'):
    """
    Automatically discover trading result files in results directory.
    """
    if not os.path.exists(results_dir):
        print(f"Error: {results_dir} directory not found")
        return [], [], []

    available_agents = set()
    available_assets = set()
    available_models = set()

    for filename in os.listdir(results_dir):
        parsed = parse_result_filename(filename)
        if parsed is None:
            continue

        agent, asset, model = parsed
        available_agents.add(agent)
        available_assets.add(asset)
        available_models.add(model)

    return sorted(available_agents), sorted(available_assets), sorted(available_models)

def find_result_files(results_dir='results', agent=None, asset=None, model=None):
    """Find trading result files matching the provided filters."""
    matches = []

    if not os.path.exists(results_dir):
        print(f"Error: {results_dir} directory not found")
        return matches

    for filename in sorted(os.listdir(results_dir)):
        parsed = parse_result_filename(filename)
        if parsed is None:
            continue

        file_agent, file_asset, file_model = parsed
        if agent and file_agent != agent:
            continue
        if asset and file_asset != asset:
            continue
        if model and file_model != model:
            continue

        matches.append({
            'agent': file_agent,
            'asset': file_asset,
            'model': file_model,
            'path': os.path.join(results_dir, filename),
        })

    return matches

def analyze_and_print(title, recommendations, asset_type='stock', symbol=None, agent=None, model=None, asset=None):
    """Analyze and print strategy performance comparison
    
    Returns:
        list: List of dictionaries containing results for each strategy
    """
    print(f"\n{'='*60}")
    print(f"{title:^60}")
    print(f"{'='*60}")
    
    results = []
    
    if not recommendations:
        print("No recommendations to analyze.")
        return results

    # Calculate Buy & Hold strategy (calculate only once)
    bh_series = calculate_buy_and_hold_series(recommendations, asset_type=asset_type, symbol=symbol)
    bh_metrics = calculate_metrics(bh_series, recommendations, asset_type=asset_type, bh_series=None)

    # Strategy 1 (HOLD keeps position) is intentionally disabled.
    # ls_keep_current = run_compounding_simulation(
    #     recommendations, strategy='long_short', trading_mode='normal',
    #     asset_type=asset_type, symbol=symbol
    # )
    # lo_keep_current = run_compounding_simulation(
    #     recommendations, strategy='long_only', trading_mode='normal',
    #     asset_type=asset_type, symbol=symbol
    # )
    # ls_metrics = calculate_metrics(
    #     ls_keep_current, recommendations, asset_type=asset_type, bh_series=bh_series
    # )
    # lo_metrics = calculate_metrics(
    #     lo_keep_current, recommendations, asset_type=asset_type, bh_series=bh_series
    # )
    # print("\nStrategy 1 (HOLD keeps position):")
    # strategies_data = [
    #     ('Long/Short', ls_metrics),
    #     ('Long-Only', lo_metrics),
    #     ('Buy & Hold', bh_metrics)
    # ]
    # print_metrics_table(strategies_data, None)

    # Strategy 2: HOLD KEEP FLAT (force close position)
    ls_keep_flat = run_compounding_simulation(recommendations, strategy='long_short', trading_mode='aggressive', asset_type=asset_type, symbol=symbol)
    lo_keep_flat = run_compounding_simulation(recommendations, strategy='long_only', trading_mode='aggressive', asset_type=asset_type, symbol=symbol)
    
    # Calculate metrics for Strategy 2 (with buy-and-hold comparison)
    ls_flat_metrics = calculate_metrics(ls_keep_flat, recommendations, asset_type=asset_type, bh_series=bh_series)
    lo_flat_metrics = calculate_metrics(lo_keep_flat, recommendations, asset_type=asset_type, bh_series=bh_series)
    
    # Print only the aggressive / HOLD forces flat strategy
    print("\nStrategy (HOLD forces flat):")
    strategies_data = [
        ('Long/Short', ls_flat_metrics),
        ('Long-Only', lo_flat_metrics),
        ('Buy & Hold', bh_metrics)
    ]
    print_metrics_table(strategies_data, None)
    
    # Add Strategy 2 results to results list
    if agent and model and asset:
        results.append({
            'agent': agent,
            'model': model,
            'asset': asset,
            'strategy': 'Long/Short',
            'trading_mode': 'aggressive',
            'total_return': ls_flat_metrics.get('total_return', 0),
            'ann_return': ls_flat_metrics.get('ann_return', 0),
            'ann_vol': ls_flat_metrics.get('ann_vol', 0),
            'sharpe_ratio': ls_flat_metrics.get('sharpe_ratio', 0),
            'max_drawdown': ls_flat_metrics.get('max_drawdown', 0),
            'days_outperforming_bh': ls_flat_metrics.get('days_outperforming_bh', 0),
            'avg_daily_excess_return': ls_flat_metrics.get('avg_daily_excess_return', 0)
        })
        results.append({
            'agent': agent,
            'model': model,
            'asset': asset,
            'strategy': 'Long-Only',
            'trading_mode': 'aggressive',
            'total_return': lo_flat_metrics.get('total_return', 0),
            'ann_return': lo_flat_metrics.get('ann_return', 0),
            'ann_vol': lo_flat_metrics.get('ann_vol', 0),
            'sharpe_ratio': lo_flat_metrics.get('sharpe_ratio', 0),
            'max_drawdown': lo_flat_metrics.get('max_drawdown', 0),
            'days_outperforming_bh': lo_flat_metrics.get('days_outperforming_bh', 0),
            'avg_daily_excess_return': lo_flat_metrics.get('avg_daily_excess_return', 0)
        })
    
    print(f"{asset_type.upper()} {symbol} | {recommendations[0]['date']} to {recommendations[-1]['date']} | {len(ls_keep_flat)} days")
    
    return results

def main():
    """Main function to run the analysis"""
    parser = argparse.ArgumentParser(
        description='Analyze trading returns from results/*.json files'
    )
    parser.add_argument('--agent', help='Filter by agent name, e.g. base_agent')
    parser.add_argument('--asset', help='Filter by asset name, e.g. AAPL')
    parser.add_argument('--model', help='Filter by model name, e.g. llama-3.3-70b')
    parser.add_argument('--results-dir', default='results', help='Directory containing result JSON files')
    args = parser.parse_args()

    print("🔍 Scanning trading result files...")
    matched_files = find_result_files(
        results_dir=args.results_dir,
        agent=args.agent,
        asset=args.asset,
        model=args.model,
    )

    if not matched_files:
        print("⚠️ No matching trading result files found")
        return

    available_agents, available_assets, available_models = discover_available_files(args.results_dir)
    print(f"Available agents: {available_agents}")
    print(f"Available assets: {available_assets}")
    print(f"Available models: {available_models}")
    print(f"Matched files: {[os.path.basename(item['path']) for item in matched_files]}")

    all_results = []

    for item in matched_files:
        agent = item['agent']
        asset = item['asset']
        model = item['model']
        file_path = item['path']

        symbol = asset
        if asset in ['BTC', 'ETH', 'ADA', 'SOL', 'DOT', 'LINK', 'UNI', 'MATIC', 'AVAX', 'ATOM']:
            asset_type = 'crypto'
        elif asset in ['TSLA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'NFLX', 'AMD', 'INTC']:
            asset_type = 'stock'
        else:
            asset_type = 'stock'

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            recs = data.get('recommendations', [])
            if not recs:
                print(f"No recommendations found in {file_path}")
                continue

            valid_format = True
            for rec in recs:
                if 'date' not in rec or 'price' not in rec:
                    print(f"Invalid recommendation format in {file_path}")
                    valid_format = False
                    break

            if not valid_format:
                continue

            recs.sort(key=lambda x: datetime.fromisoformat(x['date']))

            title = f"{agent}_{asset}_{model} ({data.get('start_date', 'Unknown')} to {data.get('end_date', 'Unknown')})"
            results = analyze_and_print(
                title,
                recs,
                asset_type=asset_type,
                symbol=symbol,
                agent=agent,
                model=model,
                asset=asset,
            )
            all_results.extend(results)

        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            continue

    # Save results to CSV
    if all_results:
        results_df = pd.DataFrame(all_results)
        results_df.to_csv('results.csv', index=False, encoding='utf-8')
        print(f"\n✅ Results saved to results.csv ({len(all_results)} rows)")
    else:
        print("\n⚠️ No results to save")
    
    # Clear price cache to free memory
    clear_price_cache()

if __name__ == "__main__":
    main()
