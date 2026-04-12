import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from '@/components/Common/ProtectedRoute'
import Layout from '@/components/Common/Layout'

import LoginPage           from '@/pages/LoginPage'
import DashboardPage       from '@/pages/DashboardPage'
import BotsListPage        from '@/pages/BotsListPage'
import BotEditPage         from '@/pages/BotEditPage'
import BotActivityPage     from '@/pages/BotActivityPage'
import BotOptimizerPage   from '@/pages/BotOptimizerPage'
import PositionsPage       from '@/pages/PositionsPage'
import AnalyticsPage       from '@/pages/AnalyticsPage'
import ChartPage           from '@/pages/ChartPage'
import ExchangeAccountsPage from '@/pages/ExchangeAccountsPage'
import ExchangeTradesPage  from '@/pages/ExchangeTradesPage'
import ManualTradePage     from '@/pages/ManualTradePage'
import PaperTradingPage    from '@/pages/PaperTradingPage'
import SettingsPage        from '@/pages/SettingsPage'
import UsersPage           from '@/pages/UsersPage'

const guard = (Page) => (
  <ProtectedRoute>
    <Layout>
      <Page />
    </Layout>
  </ProtectedRoute>
)

export default function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login"                        element={<LoginPage />} />
        <Route path="/"                             element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard"                    element={guard(DashboardPage)} />
        <Route path="/bots"                         element={guard(BotsListPage)} />
        <Route path="/bots/new"                     element={guard(BotEditPage)} />
        <Route path="/bots/:botId/edit"             element={guard(BotEditPage)} />
        <Route path="/bots/:botId/activity"         element={guard(BotActivityPage)} />
        <Route path="/bots/:botId/optimizer"        element={guard(BotOptimizerPage)} />
        <Route path="/positions"                    element={guard(PositionsPage)} />
        <Route path="/analytics"                    element={guard(AnalyticsPage)} />
        <Route path="/chart"                        element={guard(ChartPage)} />
        <Route path="/exchange-accounts"            element={guard(ExchangeAccountsPage)} />
        <Route path="/exchange-trades"              element={guard(ExchangeTradesPage)} />
        <Route path="/manual-trading"               element={guard(ManualTradePage)} />
        <Route path="/paper-trading"                element={guard(PaperTradingPage)} />
        <Route path="/users"                        element={guard(UsersPage)} />
        <Route path="/settings"                     element={guard(SettingsPage)} />
        <Route path="*"                             element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
