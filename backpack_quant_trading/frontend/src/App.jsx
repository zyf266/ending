import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import MainLayout from './layouts/MainLayout'
import Login from './views/Login'
import Dashboard from './views/Dashboard'
import Trading from './views/Trading'
import AiLab from './views/AiLab'
import GridTrading from './views/GridTrading'
import CurrencyMonitor from './views/CurrencyMonitor'
import StockAi from './views/StockAi'
import AiStock from './views/AiStock'
import AiStockDetail from './views/AiStockDetail'
import AiStockSignals from './views/AiStockSignals'
import AiStockNewsHistory from './views/AiStockNewsHistory'
import StrategyMatrixAlt from './views/StrategyMatrixAlt'
import EthTrendStrategy from './views/EthTrendStrategy'
import PaxgTrendStrategy from './views/PaxgTrendStrategy'
import Nas100TrendStrategy from './views/Nas100TrendStrategy'
import EthOnlyStrategy from './views/EthOnlyStrategy'
import OkxConsole from './views/OkxConsole'
import UsMomentumIntcStrategy from './views/UsMomentumIntcStrategy'
import UsMomentumNvdaStrategy from './views/UsMomentumNvdaStrategy'
import AShareMomentumStrategy from './views/AShareMomentumStrategy'
import UsWeeklyReport from './views/UsWeeklyReport'
import StockNewsAlert from './views/StockNewsAlert'
import PolymarketAlert from './views/PolymarketAlert'
import CryptoSignalHub from './views/CryptoSignalHub'

const RequireAuth = ({ children }) => {
  const token = localStorage.getItem('token')
  if (!token) {
    return <Navigate to="/login" replace />
  }
  return children
}

const GuestOnly = ({ children }) => {
  const token = localStorage.getItem('token')
  if (token) {
    return <Navigate to="/" replace />
  }
  return children
}

function App() {
  return (
    <>
      <Routes>
        <Route
          path="/login"
          element={
            <GuestOnly>
              <Login />
            </GuestOnly>
          }
        />

        <Route
          path="/"
          element={
            <RequireAuth>
              <MainLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="trading" replace />} />
          <Route path="trading" element={<Trading />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="ai-lab" element={<AiLab />} />
          <Route path="grid-trading" element={<GridTrading />} />
          <Route path="currency-monitor" element={<CurrencyMonitor />} />
          <Route path="stock-ai" element={<StockAi />} />
          <Route path="ai-stock" element={<AiStock />} />
          <Route path="ai-stock/:code" element={<AiStockDetail />} />
          <Route path="ai-stock/:code/signals" element={<AiStockSignals />} />
          <Route path="ai-stock/:code/news" element={<AiStockNewsHistory />} />
          <Route path="strategies" element={<StrategyMatrixAlt />} />
          <Route path="strategies/eth-trend" element={<EthTrendStrategy />} />
          <Route path="strategies/eth-only" element={<EthOnlyStrategy />} />
          <Route path="strategies/paxg-trend" element={<PaxgTrendStrategy />} />
          <Route path="strategies/nas100-trend" element={<Nas100TrendStrategy />} />
          <Route path="strategies/a-share-300308" element={<AShareMomentumStrategy code="300308" />} />
          <Route path="strategies/a-share-603986" element={<AShareMomentumStrategy code="603986" />} />
          <Route path="strategies/a-share-688146" element={<AShareMomentumStrategy code="688146" />} />
          <Route path="strategies/a-share-002837" element={<AShareMomentumStrategy code="002837" />} />
          <Route path="strategies/us-momentum-intc" element={<UsMomentumIntcStrategy />} />
          <Route path="strategies/us-momentum-nvda" element={<UsMomentumNvdaStrategy />} />
          <Route path="okx-console" element={<OkxConsole />} />
          <Route path="us-weekly-report" element={<UsWeeklyReport />} />
          <Route path="stock-news-alert" element={<StockNewsAlert />} />
          <Route path="polymarket-alert" element={<PolymarketAlert />} />
          <Route path="crypto-signal-hub" element={<CryptoSignalHub />} />
        </Route>
      </Routes>
    </>
  )
}

export default App

