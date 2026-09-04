import { useEffect } from "react";
import { Navigate } from "react-router-dom";
import { useToast } from "../components/ui/Toast";

/** `/portfolio` (rebuild spec section 4.6, D7) -- the cross-repository
 * portfolio view was cut from the product entirely, not moved. A visitor
 * following an old link lands on the dashboard instead of a bare 404, with
 * a one-time toast explaining the removal rather than silently vanishing. */
export function PortfolioRedirect() {
  const showToast = useToast();

  useEffect(() => {
    showToast("Portfolio has been removed — see your repositories on the dashboard instead.");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <Navigate to="/dashboard" replace />;
}
