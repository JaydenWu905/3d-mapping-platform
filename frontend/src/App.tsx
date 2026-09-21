import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { JobsPage } from './pages/JobsPage';
import { NewJobPage } from './pages/NewJobPage';
import { JobDetailPage } from './pages/JobDetailPage';

export default function App() {
  return (
    <BrowserRouter>
      <div className="layout">
        <Sidebar />
        <main className="main">
          <Routes>
            <Route path="/" element={<JobsPage />} />
            <Route path="/jobs/new" element={<NewJobPage />} />
            <Route path="/jobs/:jobId" element={<JobDetailPage />} />
            <Route path="*" element={<JobsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}