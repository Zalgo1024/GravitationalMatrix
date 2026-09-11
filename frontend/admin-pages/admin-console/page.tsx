import { redirect } from "next/navigation";

export default function AdminConsoleIndex() {
  redirect("/admin-console/overview");
}