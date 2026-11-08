import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="page-container text-center py-12">
      <div className="empty-state-card">
        <h1 className="text-4xl font-bold mb-2">404</h1>
        <h2>Page Not Found</h2>
        <p className="text-muted mt-2 mb-6">
          The requested ledger page or financial record does not exist or has been moved.
        </p>
        <div>
          <Link to="/" className="btn btn-primary">
            Return to Dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}
