import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="empty-state">
      <h2>That route is outside the new dashboard.</h2>
      <p>The React shell currently focuses on routed BLAIQ workflow surfaces.</p>
      <Link to="/overview">Return to overview</Link>
    </div>
  );
}
