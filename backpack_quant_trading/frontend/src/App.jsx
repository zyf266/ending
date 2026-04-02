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
import StrategyMatrixAlt from './views/StrategyMatrixAlt'
import EthTrendStrategy from './views/EthTrendStrategy'
import PaxgTrendStrategy from './views/PaxgTrendStrategy'
import Nas100TrendStrategy from './views/Nas100TrendStrategy'
import EthOnlyStrategy from './views/EthOnlyStrategy'
import OkxConsole from './views/OkxConsole'

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
          <Route path="strategies" element={<StrategyMatrixAlt />} />
          <Route path="strategies/eth-trend" element={<EthTrendStrategy />} />
          <Route path="strategies/eth-only" element={<EthOnlyStrategy />} />
          <Route path="strategies/paxg-trend" element={<PaxgTrendStrategy />} />
          <Route path="strategies/nas100-trend" element={<Nas100TrendStrategy />} />
          <Route path="okx-console" element={<OkxConsole />} />
        </Route>
      </Routes>
    </>
  )
}

export default App

