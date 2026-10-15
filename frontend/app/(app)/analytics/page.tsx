import { redirect } from "next/navigation";

/** Les analyses rejoignent les Conseils : « Vos meilleurs articles » (écran 22b, ADR 0074). */
export default function AnalyticsPage() {
  redirect("/insights?view=best");
}
