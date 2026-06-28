import { useAgUiInterrupts, useAgUiSubmitInterruptResponses } from "@assistant-ui/react-ag-ui";
import { useAuiState } from "@assistant-ui/react";
import { Button } from "@/components/ui/button";

export function AgUiInterruptCard() {

  const status = useAuiState( (s) => s.message.status);
  const interrupts = useAgUiInterrupts();
  const submit = useAgUiSubmitInterruptResponses();

  if (status?.type !== "requires-action" || status.reason !== "interrupt") {
    return null;
  }

  if (interrupts.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 rounded-lg border border-border bg-background p-4 text-foreground shadow-sm">
      <div className="mb-3 text-sm font-medium">Tool confirmation</div>

      {interrupts.map((interrupt) => (
        <div key={interrupt.id}>
          <div className="mb-3 text-sm">{interrupt.message}</div>

          <div className="flex justify-end gap-2">

            <Button
              className="bg-blue-600 text-white hover:bg-blue-700 focus-visible:ring-blue-500"
              onClick={() =>
                submit([
                  {
                    interruptId: interrupt.id,
                    status: "resolved",
                    payload: { approved: true },
                  },
                ])
              }
            >
              Approve
            </Button>

            <Button
              variant="outline"
              onClick={() =>
                submit([
                  {
                    interruptId: interrupt.id,
                    status: "cancelled",
                  },
                ])
              }
            >
              Deny
            </Button>

          </div>
        </div>
      ))}
    </div>
  );

}