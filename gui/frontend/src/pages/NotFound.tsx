import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Home } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20">
      <h1 className="text-2xl font-bold">Page not found</h1>
      <Button variant="outline" asChild>
        <Link to="/">
          <Home className="mr-2 h-4 w-4" />
          Back to Dashboard
        </Link>
      </Button>
    </div>
  );
}
