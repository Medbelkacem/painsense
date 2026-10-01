import React from 'react';
import { UserRound } from 'lucide-react';
import { useSession } from '../auth/session';
import { Card, EmptyState } from '../ui/Card';
import { PatientProfile } from './PatientProfile';

/** A patient account's one page: its own record, read-only, with the PDF to hand. */
export const MyRecord: React.FC = () => {
  const { user } = useSession();
  if (!user?.patient_id) {
    return (
      <Card>
        <EmptyState
          icon={<UserRound className="h-5 w-5" />}
          title="No record is linked to this account"
          sub="Ask the clinic administrator to tie this account to your patient record."
        />
      </Card>
    );
  }
  return <PatientProfile patientId={user.patient_id} />;
};
