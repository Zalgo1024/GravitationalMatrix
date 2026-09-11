import { AppShell } from "@/components/app-shell";
import { AuthGate } from "@/components/auth-gate";
import { AppStoreProvider } from "@/lib/store";

export default function ApplicationLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <AppStoreProvider>
        <AppShell>{children}</AppShell>
      </AppStoreProvider>
    </AuthGate>
  );
}
