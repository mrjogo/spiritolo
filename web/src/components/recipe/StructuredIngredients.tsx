import { Link } from 'react-router-dom';
import type { RecipeIngredientRow } from '../../types';

interface Props {
  rawLines: string[];
  parsedByPosition: Map<number, RecipeIngredientRow> | null;
}

export function StructuredIngredients({ rawLines, parsedByPosition }: Props) {
  const isAdmin = parsedByPosition !== null;

  return (
    <table className="recipe-detail__structured">
      {isAdmin && (
        <thead>
          <tr>
            <th>Recipe</th>
            <th>Amount</th>
            <th>Name</th>
            <th>Modifier</th>
            <th>Role</th>
            <th aria-label="ID" />
          </tr>
        </thead>
      )}
      <tbody>
        {rawLines.map((raw, i) => (
          <tr key={i}>
            <td className="recipe-detail__structured-raw">{raw}</td>
            {isAdmin && <ParsedCells row={parsedByPosition!.get(i) ?? null} />}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ParsedCells({ row }: { row: RecipeIngredientRow | null }) {
  if (row === null) {
    return (
      <td className="recipe-detail__structured-missing" colSpan={5}>
        <em>not parsed</em>
      </td>
    );
  }
  if (row.parse_status === 'unparseable') {
    return (
      <td className="recipe-detail__structured-unparseable" colSpan={5}>
        <em>unparseable</em>
      </td>
    );
  }
  return (
    <>
      <td>{formatAmount(row)}</td>
      <td>
        {row.taxonomy_nodes != null ? (
          <Link to={`/taxonomy?node=${row.taxonomy_nodes.slug}`}>
            {row.taxonomy_nodes.display_name}
          </Link>
        ) : (
          <>
            {row.name ?? ''}
            <span className="recipe-detail__structured-chip-unmapped">unmapped</span>
          </>
        )}
      </td>
      <td>{row.modifier ?? ''}</td>
      <td>
        {row.role && (
          <span className={`recipe-detail__structured-role recipe-detail__structured-role--${row.role}`}>
            {row.role}
          </span>
        )}
      </td>
      <td className="recipe-detail__structured-id">{row.id}</td>
    </>
  );
}

function formatAmount(row: RecipeIngredientRow): string {
  if (row.amount == null) return '';
  const num = row.amount_max != null ? `${row.amount}–${row.amount_max}` : String(row.amount);
  return row.unit ? `${num} ${row.unit}` : num;
}
