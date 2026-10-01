import React from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useSession } from './session';

/**
 * Gate for the authenticated workspace.
 *
 * While the refresh-cookie exchange is still in flight nothing is rendered and nothing is
 * redirected: redirecting on an unsettled session would bounce a signed-in user to the
 * sign-in page on every reload.
 */
export const RequireSession: React.FC = () => {
  const { user, restoring } = useSession();
  const location = useLocation();

  if (restoring) {
    return (
      <div className="grid min-h-dvh place-items-center bg-canvas text-[13px] text-mute">
        Restoring session…
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
};
