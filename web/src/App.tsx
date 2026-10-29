import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from '@/components/Layout'
import HomePage from '@/pages/HomePage'
import KnowledgePage from '@/pages/KnowledgePage'
import InterviewPage from '@/pages/InterviewPage'
import BankPage from '@/pages/BankPage'
import ReviewPage from '@/pages/ReviewPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 首页：全屏沉浸式，不套用顶部导航 */}
        <Route path="/" element={<HomePage />} />
        {/* 功能页：套用带顶部导航的 Layout */}
        <Route
          path="/*"
          element={
            <Layout>
              <Routes>
                <Route path="/knowledge" element={<KnowledgePage />} />
                <Route path="/interview" element={<InterviewPage />} />
                <Route path="/bank" element={<BankPage />} />
                <Route path="/review" element={<ReviewPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Layout>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}

export default App
