import React, { memo } from 'react'

/**
 * TradingView 高级图表嵌入组件
 * - 使用 iframe 嵌入 www.tradingview.com（主域名国内可访问，不依赖 s3 CDN）
 */
function TradingViewWidget({
  symbol   = 'NASDAQ:CRCL',
  interval = 'D',
  theme    = 'light',
  height   = 460,
}) {
  // 构建 iframe 嵌入地址
  const encodedSymbol = encodeURIComponent(symbol)
  const src = [
    'https://www.tradingview.com/widgetembed/',
    `?frameElementId=tv_chart_${encodedSymbol}`,
    `&symbol=${encodedSymbol}`,
    `&interval=${interval}`,
    `&theme=${theme}`,
    `&style=1`,
    `&locale=en`,
    `&toolbar_bg=%23f1f3f6`,
    `&enable_publishing=false`,
    `&allow_symbol_change=true`,
    `&hide_side_toolbar=0`,
    `&withdateranges=1`,
    `&save_image=1`,
  ].join('')

  return (
    <iframe
      src={src}
      style={{ width: '100%', height: `${height}px`, border: 'none' }}
      allowTransparency="true"
      scrolling="no"
      allowFullScreen
      title={`TradingView ${symbol}`}
    />
  )
}

export default memo(TradingViewWidget)
