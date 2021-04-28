"""The data.filters module contains core classes for filters used in data pipelines.

TODO add docstrings for all filters
TODO add unittests for all filters
"""

import csv
import collections
import itertools
import json

from collections import defaultdict
from abc import ABC, abstractmethod
from typing import Generic, Hashable, Iterable, TypeVar, Any, Sequence, Union, Tuple, cast, Dict, List

from requests import Response

from coba.data.encoders import Encoder, OneHotEncoder, NumericEncoder, StringEncoder
from coba.json import CobaJsonEncoder, CobaJsonDecoder
from coba.tools import CobaConfig
import re

# one dict for all rows, one dict for each row
# one dict for all columns, one dict for each column

_T_DenseData  = Sequence[Any]
_T_SparseData = Tuple[Sequence[int], Sequence[Any]]
_T_Data       = Union[_T_DenseData, _T_SparseData]

_T_out = TypeVar("_T_out", bound=Any, covariant=True)
_T_in  = TypeVar("_T_in", bound=Any, contravariant=True)

def _is_dense(items: Iterable[_T_Data])-> Tuple[bool, Iterable[_T_Data]]:

    items = iter(items)
    item0 = next(items)

    #a sparse item has the following structure ([ids], [values])
    #this check isn't full proof but I think should be good enough
    is_dense = (len(item0) != 2) or not all([isinstance(i, collections.Sequence) for i in item0])

    return is_dense, itertools.chain([item0], items)

class Filter(ABC, Generic[_T_in, _T_out]):
    @abstractmethod
    def filter(self, item:_T_in) -> _T_out:
        ...

class Cartesian(Filter[Union[Any,Iterable[Any]], Iterable[Any]]):

    def __init__(self, filter: Union[Filter,Sequence[Filter]]):
        
        self._filters = filter if isinstance(filter, collections.Sequence) else [filter]

    def filter(self, item: Union[Any,Iterable[Any]]) -> Iterable[Any]:

        items = item if isinstance(item, collections.Iterable) else [item]
        
        for item in items:
            for filter in self._filters:
                yield filter.filter(item)

class IdentityFilter(Filter[Any, Any]):
    def filter(self, item:Any) -> Any:
        return item

class StringJoin(Filter[Iterable[str], str]):

    def __init__(self, separator:str = '') -> None:
        self._separator = separator

    def filter(self, item: Iterable[str]) -> str:
        return self._separator.join(item)

class ResponseToText(Filter[Response, str]):
    def filter(self, item: Response) -> str:
        
        if item.status_code != 200:
            message = (
                f"The response from {item.url} reported an error. "
                "The status and reason were {item.status_code}-{item.reason}.")
            
            raise Exception(message) from None

        return item.content.decode('utf-8')

class JsonEncode(Filter[Any, str]):
    def __init__(self, encoder: json.encoder.JSONEncoder = CobaJsonEncoder()) -> None:
        self._encoder = encoder

    def filter(self, item: Any) -> str:
        return self._encoder.encode(item)

class JsonDecode(Filter[str, Any]):
    def __init__(self, decoder: json.decoder.JSONDecoder = CobaJsonDecoder()) -> None:
        self._decoder = decoder

    def filter(self, item: str) -> Any:
        return self._decoder.decode(item)

class ColSplitter(Filter[Iterable[Sequence[Any]], Tuple[Iterable[Sequence[Any]], Iterable[Sequence[Any]]]]):
    
    def __init__(self, split1_columns: Union[Sequence[int],Sequence[str]] = []):
        self._split1_columns    = split1_columns
        self._is_column_headers = len(split1_columns) > 0 and isinstance(split1_columns[0],str)

    def filter(self, columns: Iterable[Sequence[Any]]) -> Tuple[Iterable[Sequence[Any]], Iterable[Sequence[Any]]]:

        split1 = []
        split2 = []

        for index, raw_col in enumerate(columns): 

            is_split1_header =     self._is_column_headers and (raw_col[0] in self._split1_columns) 
            is_split1_index  = not self._is_column_headers and (index      in self._split1_columns)

            if is_split1_header or is_split1_index:
                split1.append(raw_col)
            else:
                split2.append(raw_col)
                
        return (split1, split2)

class ColRemover(Filter[Iterable[Sequence[Any]], Iterable[Sequence[Any]]]):
    def __init__(self, remove_columns: Union[Sequence[int],Sequence[str]] = []):
        
        self._removed_columns = remove_columns
        self._is_column_headers = len(remove_columns) > 0 and isinstance(remove_columns[0],str)

    def filter(self, columns: Iterable[Sequence[Any]]) -> Iterable[Sequence[Any]]:

        for index, raw_col in enumerate(columns):

            is_ignored_header =     self._is_column_headers and (raw_col[0] in self._removed_columns) 
            is_ignored_index  = not self._is_column_headers and (index      in self._removed_columns)

            if not is_ignored_header and not is_ignored_index:
                yield raw_col

class ColEncoder(Filter[Iterable[Sequence[str]], Iterable[Sequence[Any]]]):

    def __init__(self, headers: Sequence[str] = [], encoders: Sequence[Encoder] = [], default: Encoder = None) -> None:

        assert len(headers) == 0 or len(encoders) <= len(headers), "The given encoders didn't match the given headers."
        assert len(encoders) > 0 or default is not None, "A valid encoder was not provided to ColEncoder."

        self._encoders = encoders
        self._headers  = headers
        self._default  = default

    def filter(self, columns: Iterable[Sequence[str]]) -> Iterable[Sequence[Any]]:

        for index, raw_col in enumerate(columns):

            raw_hdr  = raw_col[0]
            raw_vals = raw_col[1:]

            encoder = self._get_encoder(index, raw_hdr)
            encoder = encoder if encoder.is_fit else encoder.fit(raw_vals)

            encoded_values: Sequence[Hashable]

            if isinstance(encoder, OneHotEncoder):
                encoded_values = list(zip(*encoder.encode(raw_vals)))
            else:
                encoded_values = list(encoder.encode(raw_vals))

            yield [cast(Hashable,raw_hdr)] + encoded_values

    def _get_encoder(self, index: int, header: str) -> Encoder:

        encoded_headers = self._headers[0:len(self._encoders)]

        if header in encoded_headers:
            return self._encoders[encoded_headers.index(header)]

        if len(encoded_headers) == 0 and index < len(self._encoders):
            return self._encoders[index]

        if self._default is not None:
            return self._default

        raise Exception("We were unable to find an encoder for the column.")

class RowRemover(Filter[Iterable[Sequence[Any]], Iterable[Sequence[Any]]]):
    def __init__(self, remove_rows: Sequence[int] = []):
        self._remove_rows = remove_rows

    def filter(self, items: Iterable[Sequence[Any]]) -> Iterable[Sequence[Any]]:
        for i, item in enumerate(items):
            if i not in self._remove_rows:
                yield item

class CsvReader(Filter[Iterable[str], Iterable[_T_DenseData]]):
    def filter(self, items: Iterable[str]) -> Iterable[Sequence[str]]:
        return filter(None,csv.reader(items))

class CsvTranspose(Filter[Iterable[_T_DenseData], Iterable[_T_DenseData]]):
    def __init__(self, flatten: bool = False):
        self._flatten = flatten

    def filter(self, items: Iterable[Sequence[_T_in]]) -> Iterable[Sequence[_T_out]]:

        #row 1 has these dictj[col_id, value]...
        #col 1 has these dict[row_id, value]...
        #if we force column ids to be numeric in the sparse case then transpose is well defined...

        #sequence[dict] -> dict[sequences]

        items = filter(None, items)
        items = items if not self._flatten else self._flatter(items)

        return zip(*list(items)) #type: ignore

    def _flatter(self, items: Iterable[Sequence[_T_in]]) -> Iterable[Sequence[_T_in]]:
        for item in items:
            if isinstance(item[1], collections.Sequence) and not isinstance(item[1], str):
                for i in item[1:]:
                    yield [item[0]] + list(i)
            else:
                yield item

class Transpose(Filter[Iterable[_T_Data], Iterable[_T_Data]]):
    def filter(self, items: Iterable[_T_Data]) -> Iterable[_T_Data]:

        is_dense,items =_is_dense(items)

        if is_dense:
            return zip(*items)
        else:
            sparse_transposed_items = defaultdict( lambda: ([],[]))

            for outer_id, item in enumerate(items):
                for inner_id, value in zip(item[0], item[1]):
                    sparse_transposed_items[inner_id][0].append(outer_id)
                    sparse_transposed_items[inner_id][1].append(value)

            return list(sparse_transposed_items.values())

class Flatten(Filter[Iterable[_T_Data], Iterable[_T_Data]]):
    def filter(self, items: Iterable[Sequence[Any]]) -> Iterable[Sequence[Any]]:
        is_dense,items =_is_dense(items)
        
        return map(self._flat, items) if is_dense else items

    def _flat(self, item: Union[Sequence[Any], Any]) -> Sequence[Any]:
        return sum(map(self._flat, item),[]) if isinstance(item, collections.Sequence) else [item]

    def _flatter(self, items: Iterable[Sequence[Any]]) -> Iterable[Sequence[Any]]:
        for item in items:
            if isinstance(item[1], collections.Sequence) and not isinstance(item[1], str):
                for i in item[1:]:
                    yield [item[0]] + list(i)
            else:
                yield item

class Encode(Filter[Iterable[_T_Data],Iterable[_T_Data]]):

    def __init__(self, encoders: Sequence[Encoder]):
        self._encoders = encoders

    def filter(self, items: Iterable[_T_Data]) -> Iterable[_T_Data]:
        
        is_dense,items =_is_dense(items)

        for encoder, column in zip(self._encoders, items):

            raw_values = column if is_dense else column[1]

            encoder = encoder if encoder.is_fit else encoder.fit(raw_values)

            encoded_values = encoder.encode(raw_values)

            yield encoder.encode(raw_values) if is_dense else (column[0], encoded_values)

class CsvCleaner(Filter[Iterable[str], Iterable[Sequence[Any]]]):

    def __init__(self,
        headers: Sequence[str] = [],
        encoders: Sequence[Encoder] = [],
        default: Encoder = None,
        ignored: Sequence[bool] = [],
        output_rows: bool = True):

        self._headers  = headers
        self._encoders = encoders
        self._default  = default
        self._ignored  = ignored
        self._output_rows = output_rows

    def filter(self, items: Iterable[str]) -> Iterable[Sequence[Any]]:

        ignored_headers = list(itertools.compress(self._headers, self._ignored))

        cleaning_steps: Sequence[Filter] = [
            CsvTranspose(), ColRemover(ignored_headers), ColEncoder(self._headers, self._encoders, self._default)
        ]

        output: Any = items
        
        for cleaning_step in cleaning_steps: output = cleaning_step.filter(output)
        return output if not self._output_rows else CsvTranspose().filter(output)

class LabeledCsvCleaner(Filter[Iterable[Sequence[str]], Tuple[Iterable[Sequence[Any]],Iterable[Sequence[Any]]]]):
    def __init__(self, 
        label_col : Union[int,str],
        headers   : Sequence[str]     = [],
        encoders  : Sequence[Encoder] = [], 
        ignored   : Sequence[bool]    = [],
        rmv_header: bool              = False):

        self._label_col  = label_col
        self._encoders   = encoders
        self._headers    = headers
        self._ignored    = ignored
        self._rmv_header = rmv_header

    def filter(self, items: Iterable[Sequence[str]]) -> Tuple[Iterable[Sequence[Any]],Iterable[Sequence[Any]]]:

        split_column = cast(Union[Sequence[str],Sequence[int]], [self._label_col])

        clean      = CsvCleaner(self._headers, self._encoders, None, self._ignored, output_rows=False)
        split      = ColSplitter(split_column)
        rows       = Cartesian(CsvTranspose(True))
        rmv_header = Cartesian(RowRemover([0]))

        output: Any = items

        with CobaConfig.Logger.time('encoding data... '):

            output = rows.filter(split.filter(clean.filter(output)))

            if self._rmv_header: 
                output = rmv_header.filter(output)

            labels   = next(output)
            features = next(output)

            return features, labels

class ArffReader(Filter):
    # Takes in ARFF bytes and splits it into attributes, encoders, and data while handling sparse data

    def __init__(self,
        label_col : str,
        ignored   : Sequence[bool]    = [],
        rmv_header: bool              = True):

        self._label_col  = label_col
        self._ignored = ignored
        self._rmv_header = rmv_header

        # Match a comment
        self._r_comment = re.compile(r'^%')
        # Match an empty line
        self.r_empty = re.compile(r'^\s+$')
        # Match a header line, that is a line which starts by @ + a word
        self._r_headerline = re.compile(r'^\s*@\S*')

        self._r_datameta = re.compile(r'^@[Dd][Aa][Tt][Aa]')
        self._r_relation = re.compile(r'^@[Rr][Ee][Ll][Aa][Tt][Ii][Oo][Nn]\s*(\S*)')
        self._r_attribute = re.compile(r'^\s*@[Aa][Tt][Tt][Rr][Ii][Bb][Uu][Tt][Ee]\s*(..*$)')

    def _read_header(self, source: List[str]):
        """Reads in raw arff string

        Args
            source:      source bytes returned from openML api call
        Ret
            relation:    name of arff relation
            attributes:  list of attribute (column) titles
            encoders:    list of encoders for the attributes
            data         rows of data in lists comma separated
        """

        i = 0
        # Pass first comments
        while self._r_comment.match(source[i]):
            i += 1

        # Header is everything up to DATA attribute
        relation = None
        attributes = []
        encoders = []
        while not self._r_datameta.match(source[i]):
            m = self._r_headerline.match(source[i])
            if m:
                isattr = self._r_attribute.match(source[i])
                if isattr:
                    attr_string = isattr.group(1).lower().strip()
                    i += 1
                    tipe = re.split('[ ]',attr_string, 1)[1]
                    attr = re.split('[ ]',attr_string)[0]
                    if (tipe=='numeric' or tipe=='integer' or tipe=='real'):
                        encoders.append(NumericEncoder())
                    elif ('{' in tipe):
                        tipe = re.sub(r'[{}]', '', tipe)
                        vals = re.split(', ', tipe, 1)
                        if(self._label_col != attr):
                            encoders.append(OneHotEncoder(singular_if_binary=True))
                        else:
                            encoders.append(OneHotEncoder())
                    else:
                        encoders.append(StringEncoder())

                    attributes.append(attr)
                else:
                    isrel = self._r_relation.match(source[i])
                    if isrel:
                        relation = isrel.group(1)
                    else:
                        raise ValueError("Error parsing line %s" % i)
                    i += 1
            else:
                i += 1
        data = source[i+1:]
        for j in range(len(data)):
            if (data[j]==''):
                data.remove(data[j])
            else:
                data[j] = re.split('[,]',data[j])
        return relation, attributes, encoders, data

    def _sparse_filler(self, items: List[List[str]], encoders: List[Encoder]) -> List[List[str]]: # Currently quite inefficient
        """Handles Sparse ARFF data

        Args
            items:      Data from openML api call as returned by read_header
            encoders:   Encoders from openML api call as returned by read_header
        Ret
            if sparse --     full:  non-sparse version of data
            if non-sparse -- items: original data
        """

        _starts_with_curly = items[0][0][0] == "{"
        _ends_with_curly = items[0][-1][-1] == "}"
        if(not _starts_with_curly or not _ends_with_curly):
            return items

        full = []
        # Creates non-sparse version of data. 
        for i in range(len(items)):
            r = []
            for encoder in encoders:
                app = ""
                if(isinstance(encoder, NumericEncoder)):
                    app = "0"
                r.append(app)
            full.append(r)

        # Fills in data from items
        for i in range(len(items)):
            items[i][0] = items[i][0].replace('{', '', 1)
            items[i][-1] = items[i][-1].replace('}', '', 1)
            for j in range(len(items[i])):
                split = re.split(' ', items[i][j], 1)
                index = int(split[0])
                val = split[1]
                full[i][index] = val
        return full

    def _clean(self, attributes, encoders, items):

        split_column = cast(Union[Sequence[str],Sequence[int]], [self._label_col])

        clean      = ArffCleaner(attributes, encoders, None, self._ignored, output_rows=False)
        split      = ColSplitter(split_column)
        rows       = Cartesian(CsvTranspose(True))
        rmv_header = Cartesian(RowRemover([0]))

        output: Any = items

        with CobaConfig.Logger.time('encoding data... '):

            output = rows.filter(split.filter(clean.filter(output)))

            if self._rmv_header: 
                output = rmv_header.filter(output)
            
            labels   = next(output)
            features = next(output)

            return features, labels

    def filter(self, source: List[str]):
    
        relation, attributes, encoders, items = self._read_header(source)
        items = self._sparse_filler(items, encoders)
        features, labels = self._clean(attributes, encoders, items)
        return features, labels

class ArffCleaner(Filter[Iterable[str], Iterable[Sequence[Any]]]):
    # Takes rows in a list of lists and converts them to encoded column form

    def __init__(self,
        attributes: Sequence[str] = [],
        encoders: Sequence[Encoder] = [],
        default: Encoder = None,
        ignored: Sequence[bool] = [],
        output_rows: bool = True):

        self._attributes  = attributes
        self._encoders = encoders
        self._default  = default
        self._ignored  = ignored
        self._output_rows = output_rows

    def filter(self, items: Iterable[str]) -> Iterable[Sequence[Any]]:

        ignored_headers = list(itertools.compress(self._attributes, self._ignored))

        cleaning_steps: Sequence[Filter] = [
            CsvTranspose(), ArffHeaderAdder(self._attributes), ColRemover(ignored_headers), ColEncoder(self._attributes, self._encoders, self._default)
        ]

        output: Any = items
        
        for cleaning_step in cleaning_steps: output = cleaning_step.filter(output)
        return output if not self._output_rows else CsvTranspose().filter(output)

class ArffHeaderAdder(Filter[Iterable[Any], Iterable[Sequence[Any]]]):
    """Adds the attribute name to each column list

    Args
        attributes:  list of attributes
    Ret
        list of attribute name and then original column values
    """ 

    def __init__(self,
        attributes):

        self._attributes = attributes

    def filter(self, columns: Iterable[Sequence[Any]]) -> Iterable[Sequence[Any]]:

        for index, raw_col in enumerate(columns):

            yield (self._attributes[index], *raw_col)
