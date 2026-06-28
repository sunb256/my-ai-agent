import { useAgUiInterrupts, useAgUiSubmitInterruptResponses } from "@assistant-ui/react-ag-ui";
import { Button } from "@/components/ui/button";

export function AgUiInterruptPanel() {
  const interrupts = useAgUiInterrupts();
  const submit = useAgUiSubmitInterruptResponses();

  if (interrupts.length === 0)
    return null;

  return (
    <div className="fixed right-4 bottom-4 z-50 w-96 rounded-lg border border-border bg-background p-4 text-foreground shadow-lg">
      <div className="mb-3 text-sm font-medium">Tool confirmation</div>

      {interrupts.map((interrupt) => (
        <div key={interrupt.id}>
          <div className="mb-3 text-sm">{interrupt.message}</div>

            <div className="flex justify-end gap-2">

              <Button
                onClick={() =>
                  submit([
                    {
                      interruptId: interrupt.id,
                      status: "resolved",
                      payload: { approved: true },
                    },
                  ])
                }
              >Approve</Button>

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
              >Deny</Button>

            </div>
          </div>

      ))}
    </div>
  );
}

