import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from '@/components/Layout'
import KnowledgePage from '@/pages/KnowledgePage'
import InterviewPage from '@/pages/InterviewPage'
import BankPage from '@/pages/BankPage'
import ReviewPage from '@/pages/ReviewPage'

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/interview" replace />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/interview" element={<InterviewPage />} />
          <Route path="/bank" element={<BankPage />} />
          <Route path="/review" element={<ReviewPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
