-- ====================================================================
-- FERTILITY CLINIC: SUPABASE COMPATIBILITY & ALIGNMENT MIGRATION
-- Non-destructive: Safe to run multiple times. Preserves all existing data.
-- ====================================================================

-- 1. Patients: Add WhatsApp consent tracking (defaults to false)
ALTER TABLE public.patients 
ADD COLUMN IF NOT EXISTS whatsapp_opt_in BOOLEAN NOT NULL DEFAULT false;

-- 2. Follow-ups: Add patient response status tracking
ALTER TABLE public.follow_ups 
ADD COLUMN IF NOT EXISTS patient_response TEXT;

-- 3. Reschedule Requests: Track prior status to safely restore if rejected
ALTER TABLE public.reschedule_requests 
ADD COLUMN IF NOT EXISTS previous_status TEXT;

-- 4. Messages: Add scheduling date, error details, and updated timestamp
ALTER TABLE public.messages 
ADD COLUMN IF NOT EXISTS scheduled_for_date DATE;

ALTER TABLE public.messages 
ADD COLUMN IF NOT EXISTS error TEXT;

ALTER TABLE public.messages 
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- Unique index to prevent duplicate reminders for the same follow-up on the same day
CREATE UNIQUE INDEX IF NOT EXISTS ix_messages_follow_up_date 
ON public.messages (follow_up_id, scheduled_for_date)
WHERE scheduled_for_date IS NOT NULL;

-- 5. Appointments Table (Patient Visit History)
CREATE TABLE IF NOT EXISTS public.appointments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
    appointment_date DATE NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SCHEDULED', 'ATTENDED', 'CANCELLED', 'NO_SHOW')),
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_appointments_patient 
ON public.appointments (patient_id);

-- 6. Clinic Activity & Audit Trail
CREATE TABLE IF NOT EXISTS public.activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    action TEXT NOT NULL,
    patient_id UUID REFERENCES public.patients(id) ON DELETE SET NULL,
    follow_up_id UUID REFERENCES public.follow_ups(id) ON DELETE SET NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_activity_patient 
ON public.activity (patient_id);

CREATE INDEX IF NOT EXISTS ix_activity_follow_up 
ON public.activity (follow_up_id);

-- 7. Webhook Idempotency Receipts
CREATE TABLE IF NOT EXISTS public.webhook_receipts (
    provider_message_id TEXT PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8. Row Level Security (RLS) Configuration
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.follow_ups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reschedule_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.activity ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_receipts ENABLE ROW LEVEL SECURITY;

-- 9. Role-based Policies for Staff Access
DROP POLICY IF EXISTS "Allow authenticated staff to read profiles" ON public.profiles;
CREATE POLICY "Allow authenticated staff to read profiles"
ON public.profiles FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Allow doctors to see assigned patients" ON public.patients;
CREATE POLICY "Allow doctors to see assigned patients"
ON public.patients FOR SELECT TO authenticated
USING (
  assigned_doctor_id = auth.uid() 
  OR EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role IN ('receptionist', 'admin'))
);

DROP POLICY IF EXISTS "Allow doctors to see assigned follow-ups" ON public.follow_ups;
CREATE POLICY "Allow doctors to see assigned follow-ups"
ON public.follow_ups FOR SELECT TO authenticated
USING (
  doctor_id = auth.uid() 
  OR EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role IN ('receptionist', 'admin'))
);
